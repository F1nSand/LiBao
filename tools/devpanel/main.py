"""开发面板（devpanel）：本地 Web 控制台，用一个总进程监管 backend/frontend 两个服务。

替代 start.sh / start.cmd 的多窗口方案：
- 子进程窗口全部隐藏（CREATE_NO_WINDOW），stdout/stderr 经管道收进面板；
- 日志 + 状态经 SSE 推送浏览器单页；
- 端口冲突自适应：面板自身端口被占自动 +1；服务端口已有健康服务 → 标记 external 复用，不硬起。
- 前端依赖缺失时按 package-lock.json 自动执行一次 npm ci，再启动 Vite。

单机化后不再依赖 docker/redis，仅拉起本地后端与前端两个进程。

用法：`cd tools/devpanel && uv run python main.py [--port 9100] [--no-browser]`
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import webbrowser
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse

PROJECTS_ROOT = Path(__file__).resolve().parents[2]
BACKEND = PROJECTS_ROOT / "apps" / "backend"
FRONTEND = PROJECTS_ROOT / "apps" / "frontend"
STATIC = Path(__file__).resolve().parent / "static"

WIN = sys.platform == "win32"
CREATE_NO_WINDOW = 0x08000000 if WIN else 0

BE_PORT = 8000
FE_PORT = 5173
PANEL_PORT_DEFAULT = 9100

# 状态常量
STOPPED = "stopped"
STARTING = "starting"
RUNNING = "running"
ERROR = "error"
EXTERNAL = "external"

# 可执行文件解析（Windows 上 npm 是 .cmd，改用 node 直跑 vite.js，避免 cmd 壳难终止）
_NODE = shutil.which("node")
_NPM = shutil.which("npm.cmd") or shutil.which("npm")
_UVICORN_EXE = BACKEND / ".venv" / "Scripts" / "uvicorn.exe"
_BE_EXE = _UVICORN_EXE if _UVICORN_EXE.exists() else None
_FE_ENTRY = FRONTEND / "node_modules" / "vite" / "bin" / "vite.js"


# ---------------- 工具函数 ----------------

def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        try:
            s.bind((host, port))
            return False
        except OSError:
            return True


def find_free_port(start: int, tries: int = 30) -> int:
    for p in range(start, start + tries):
        if not is_port_in_use(p):
            return p
    raise RuntimeError(f"端口 {start}~{start + tries - 1} 全部被占用")


async def _http_ok(url: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=2.0, verify=False) as c:
            return (await c.get(url)).status_code == 200
    except Exception:
        return False


# ---------------- 事件总线 ----------------

class Hub:
    """SSE 广播：publish 为同步调用（put_nowait），订阅者队列满则丢最旧。"""

    def __init__(self) -> None:
        self._subs: set[asyncio.Queue] = set()

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=3000)
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subs.discard(q)

    def publish(self, event: str, data: dict) -> None:
        payload = (event, data)
        for q in list(self._subs):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                try:
                    q.get_nowait()
                    q.put_nowait(payload)
                except Exception:
                    pass


# ---------------- 服务模型 ----------------

@dataclass
class Service:
    id: str
    label: str
    port: int
    cmd: list[str] | None = None
    cwd: Path | None = None
    extra_env: dict[str, str] | None = None
    health_url: str | None = None                # http 健康地址
    open_url: str | None = None                  # 面板"打开浏览器"的子路径（后端→/docs）

    status: str = STOPPED
    detail: str = ""
    proc: asyncio.subprocess.Process | None = None
    task: asyncio.Task | None = None
    logs: deque[str] = field(default_factory=lambda: deque(maxlen=800))
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class ServiceManager:
    def __init__(self) -> None:
        self.hub = Hub()
        self.services: dict[str, Service] = {}
        self._build()

    def _build(self) -> None:
        if _BE_EXE:
            be_cmd = [str(_BE_EXE), "app.api.main:app", "--host", "127.0.0.1", "--port", str(BE_PORT)]
        else:
            be_cmd = ["uv", "run", "uvicorn", "app.api.main:app", "--host", "127.0.0.1", "--port", str(BE_PORT)]
        self.services["backend"] = Service(
            id="backend", label="后端 API", port=BE_PORT,
            cmd=be_cmd, cwd=BACKEND,
            health_url=f"http://127.0.0.1:{BE_PORT}/api/v1/system/health",
            open_url="/docs")
        # --host 127.0.0.1：Node>=17 默认把 localhost 解析为 IPv6 ::1，Vite 会绑在 ::1
        # 导致 IPv4 健康检查/浏览器打不开；显式绑 IPv4 与面板检测、打开链接保持一致
        self.services["frontend"] = Service(
            id="frontend", label="前端", port=FE_PORT,
            cmd=[_NODE or "node", str(_FE_ENTRY), "--host", "127.0.0.1", "--port", str(FE_PORT), "--strictPort"],
            cwd=FRONTEND, extra_env={"VITE_USE_MOCK": "false"},
            health_url=f"http://127.0.0.1:{FE_PORT}/")

    # ---------- 内部 ----------

    def _log(self, svc: Service, line: str) -> None:
        line = line.rstrip("\n")
        if line:
            svc.logs.append(line)
            self.hub.publish("log", {"id": svc.id, "line": line})

    def _publish(self, svc: Service) -> None:
        self.hub.publish("status", self.svc_dict(svc))

    def svc_dict(self, svc: Service) -> dict:
        return {
            "id": svc.id,
            "label": svc.label,
            "port": svc.port,
            "status": svc.status,
            "detail": svc.detail,
            "pid": svc.proc.pid if (svc.proc and svc.proc.returncode is None) else None,
            "open_url": svc.open_url,
        }

    def snapshot(self) -> dict:
        return {"services": [self.svc_dict(s) for s in self.services.values()]}

    async def _health_ok(self, svc: Service) -> bool:
        return await _http_ok(svc.health_url) if svc.health_url else False

    async def _set(self, svc: Service, status: str, detail: str = "") -> None:
        svc.status, svc.detail = status, detail
        self._publish(svc)

    # ---------- 启动 ----------

    async def start(self, svc_id: str) -> None:
        svc = self.services[svc_id]
        async with svc.lock:
            if svc.status in (STARTING, RUNNING, EXTERNAL):
                return
            await self._start_process(svc)

    async def _ensure_frontend_dependencies(self, svc: Service) -> bool:
        """首次启动源码包时按锁文件恢复依赖，避免直接报 Vite 路径不存在。"""
        if svc.id != "frontend" or _FE_ENTRY.is_file():
            return True
        if _NODE is None:
            await self._set(svc, ERROR, "找不到 node，请先安装 Node.js")
            return False
        if _NPM is None:
            await self._set(svc, ERROR, "找不到 npm，请先安装 Node.js")
            return False
        lockfile = FRONTEND / "package-lock.json"
        if not lockfile.is_file():
            await self._set(svc, ERROR, "缺少 package-lock.json，无法自动安装前端依赖")
            return False

        if WIN:
            comspec = os.environ.get("ComSpec") or os.environ.get("COMSPEC") or "cmd.exe"
            # 直接传完整的带空格路径时，create_subprocess_exec 会把引号原样交给 cmd；
            # npm 已由 PATH 解析确认存在，让 cmd 按文件名解析可避免 Windows 引号陷阱。
            install_cmd = [comspec, "/d", "/c", f"{Path(_NPM).name} ci --ignore-scripts"]
        else:
            install_cmd = [_NPM, "ci", "--ignore-scripts"]
        await self._set(svc, STARTING, "未检测到前端依赖，正在执行 npm ci")
        self._log(svc, "$ " + " ".join(str(x) for x in install_cmd))
        try:
            proc = await asyncio.create_subprocess_exec(
                *install_cmd,
                cwd=str(FRONTEND),
                env=dict(os.environ),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                creationflags=CREATE_NO_WINDOW,
            )
        except (FileNotFoundError, OSError) as exc:
            await self._set(svc, ERROR, f"无法执行 npm ci：{exc}")
            return False

        # 将安装进程挂到服务上，面板停止或用户点“停止”时由统一回收逻辑终止它，
        # 避免 npm 尚未结束时面板退出而留下占用 node_modules 的孤儿进程。
        svc.proc = proc
        assert proc.stdout is not None
        try:
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                self._log(svc, line.decode("utf-8", errors="replace").rstrip("\n"))
            rc = await proc.wait()
        finally:
            if svc.proc is proc:
                svc.proc = None
        if rc != 0:
            await self._set(svc, ERROR, f"npm ci 失败 exit={rc}")
            return False
        if not _FE_ENTRY.is_file():
            await self._set(svc, ERROR, "npm ci 完成但仍找不到 Vite 入口")
            return False
        self._log(svc, "[devpanel] 前端依赖已按 package-lock.json 恢复")
        return True

    async def _start_process(self, svc: Service) -> None:
        if svc.health_url and await _http_ok(svc.health_url):
            await self._set(svc, EXTERNAL, f":{svc.port} 已有健康服务（外部运行）")
            self._log(svc, f"[devpanel] :{svc.port} 已运行健康服务 → 复用外部进程，不重复启动")
            return
        if is_port_in_use(svc.port):
            await self._set(svc, ERROR, f"端口 :{svc.port} 被占用且无健康响应")
            self._log(svc, f"[devpanel] 端口 :{svc.port} 被占用且未检测到健康服务，请先释放端口")
            return
        if not await self._ensure_frontend_dependencies(svc):
            return
        env = dict(os.environ)
        if svc.extra_env:
            env.update(svc.extra_env)
        self._log(svc, "$ " + " ".join(str(x) for x in svc.cmd))
        try:
            proc = await asyncio.create_subprocess_exec(
                *svc.cmd,
                cwd=str(svc.cwd) if svc.cwd else None,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                creationflags=CREATE_NO_WINDOW,
            )
        except FileNotFoundError:
            await self._set(svc, ERROR, "启动命令不存在")
            return
        svc.proc = proc
        await self._set(svc, STARTING, f"PID {proc.pid}")
        svc.task = asyncio.create_task(self._process_loop(svc, proc))

    async def _process_loop(self, svc: Service, proc: asyncio.subprocess.Process) -> None:
        async def pump() -> None:
            assert proc.stdout is not None
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                self._log(svc, line.decode("utf-8", errors="replace").rstrip("\n"))

        pump_task = asyncio.create_task(pump())
        healthy = False
        for _ in range(60):  # 最多 ~120s 等健康
            if proc.returncode is not None:
                break
            if await self._health_ok(svc):
                healthy = True
                break
            await asyncio.sleep(2)

        if healthy:
            await self._set(svc, RUNNING, f"PID {proc.pid} · :{svc.port}")
            self._log(svc, f"[devpanel] 健康检查通过 → running (:{svc.port})")
        elif proc.returncode is not None:
            await self._set(svc, ERROR, f"启动即退出 exit={proc.returncode}")
            self._log(svc, f"[devpanel] 进程启动即退出 exit={proc.returncode}")
            await pump_task
            svc.proc = None
            svc.task = None
            return
        else:
            # 超时未健康但仍在跑：按 running 处理
            await self._set(svc, RUNNING, f"PID {proc.pid} · :{svc.port}")

        rc = await proc.wait()
        await pump_task
        svc.proc = None
        svc.task = None
        if svc.status == RUNNING:
            await self._set(svc, ERROR, f"进程退出 exit={rc}")
            self._log(svc, f"[devpanel] 进程退出 exit={rc}")
        elif svc.status == STARTING:
            await self._set(svc, ERROR, f"进程退出 exit={rc}")
            self._log(svc, f"[devpanel] 进程退出 exit={rc}")

    # ---------- 停止 ----------

    async def stop(self, svc_id: str) -> None:
        svc = self.services[svc_id]
        async with svc.lock:
            if svc.status == EXTERNAL:
                await self._set(svc, STOPPED)
                return
            if svc.status not in (RUNNING, STARTING):
                return
            await self._set(svc, STOPPED)
            await self._kill_process(svc)

    async def _kill_process(self, svc: Service) -> None:
        proc = svc.proc
        if proc is None or proc.returncode is not None:
            return
        if WIN:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
        else:
            proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=8)
        except TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            await asyncio.wait_for(proc.wait(), timeout=3)
        self._log(svc, "[devpanel] 已停止")

    # ---------- 重启 / 全启全停 ----------

    async def restart(self, svc_id: str) -> None:
        await self.stop(svc_id)
        await asyncio.sleep(0.6)
        await self.start(svc_id)

    ORDER = ("backend", "frontend")

    async def start_all(self) -> None:
        for sid in self.ORDER:
            await self.start(sid)

    async def stop_all(self) -> None:
        for sid in reversed(self.ORDER):
            await self.stop(sid)

    # ---------- 启动时探测现状（面板重启后反映真实状态） ----------

    async def probe(self) -> None:
        for svc in self.services.values():
            if svc.health_url and await _http_ok(svc.health_url):
                await self._set(svc, EXTERNAL, f":{svc.port} 已有健康服务（外部运行）")

    def shutdown_processes(self) -> None:
        """面板退出：回收自己拉起的子服务进程。"""
        for svc in self.services.values():
            if svc.status in (RUNNING, STARTING):
                proc = svc.proc
                if proc and proc.returncode is None:
                    if WIN:
                        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
                    else:
                        try:
                            proc.terminate()
                        except ProcessLookupError:
                            pass


# ---------------- FastAPI 应用 ----------------

manager = ServiceManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await manager.probe()
    try:
        yield
    finally:
        manager.shutdown_processes()


app = FastAPI(title="Agent DevPanel", version="0.1.0", lifespan=lifespan)


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return (STATIC / "index.html").read_text(encoding="utf-8")


@app.get("/api/panel")
async def panel_info() -> dict:
    port = getattr(app.state, "panel_port", PANEL_PORT_DEFAULT)
    return {"port": port, "version": "0.1.0"}


@app.get("/api/services")
async def services() -> dict:
    return manager.snapshot()


@app.get("/api/events")
async def events(request: Request):
    q = manager.hub.subscribe()
    panel_port = getattr(app.state, "panel_port", PANEL_PORT_DEFAULT)

    async def gen():
        yield _sse("panel", {"port": panel_port})
        yield _sse("snapshot", manager.snapshot())
        for svc in manager.services.values():
            for line in svc.logs:
                yield _sse("log", {"id": svc.id, "line": line})
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event, data = await asyncio.wait_for(q.get(), timeout=15)
                    yield _sse(event, data)
                except TimeoutError:
                    yield ": ping\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            manager.hub.unsubscribe(q)

    return StreamingResponse(
        gen(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _act(svc_id: str, action: str) -> dict:
    if svc_id not in manager.services:
        raise HTTPException(status_code=404, detail="未知服务")
    fn = {"start": manager.start, "stop": manager.stop, "restart": manager.restart}[action]
    await fn(svc_id)
    return {"ok": True}


@app.post("/api/services/{svc_id}/{action}")
async def service_action(svc_id: str, action: str) -> dict:
    if action not in ("start", "stop", "restart"):
        raise HTTPException(status_code=400, detail="非法操作")
    return await _act(svc_id, action)


@app.post("/api/start-all")
async def start_all() -> dict:
    await manager.start_all()
    return {"ok": True}


@app.post("/api/stop-all")
async def stop_all() -> dict:
    await manager.stop_all()
    return {"ok": True}


# ---------------- 入口 ----------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Agent 开发面板")
    parser.add_argument("--port", type=int, default=PANEL_PORT_DEFAULT, help="面板端口（默认 9100）")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    args = parser.parse_args()

    panel_port = find_free_port(args.port)
    if panel_port != args.port:
        print(f"[devpanel] 默认端口 :{args.port} 被占用，改用空闲端口 :{panel_port}")
    print(f"[devpanel] 面板启动: http://127.0.0.1:{panel_port}/   (Ctrl+C 退出，同时回收子进程)")
    app.state.panel_port = panel_port

    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{panel_port}/")).start()

    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=panel_port, log_level="warning")


if __name__ == "__main__":
    main()
