"""开发面板（devpanel）：一个本地 Web 控制台，用一个总进程监管 db/redis/backend/frontend 四个服务。

替代 start.sh / start.cmd 的多窗口方案：子进程窗口全部隐藏（CREATE_NO_WINDOW），
stdout/stderr 通过管道收进面板，经 SSE 推送到浏览器单页。
"""
