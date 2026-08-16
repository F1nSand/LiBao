# 前端构建（docs/05 §2.3）：node:20-alpine build → nginx:alpine serve
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci || npm install
COPY . .
# 生产构建关闭 mock（VITE_USE_MOCK=false），/api 由 nginx 代理到后端
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
