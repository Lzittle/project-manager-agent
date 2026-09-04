# ---------- 前端镜像：Vite 构建 → Nginx 托管 + /api 反代后端 ----------
# 多阶段构建：stage1 用 node 构建出静态文件，stage2 用 nginx 托管并反代 /api。
# 阶段一：构建
FROM node:20-alpine AS build

WORKDIR /app

# 先装依赖（利用层缓存）
COPY package*.json ./
RUN npm config set registry https://registry.npmmirror.com \
    && npm ci

# 拷贝源码并构建
COPY . .
RUN npm run build

# 阶段二：运行（nginx 托管 dist + 反代）
FROM nginx:alpine

# 自定义 nginx 配置：/api → backend 服务（见 nginx.conf）
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

# 容器启动即由 nginx 托管；/api 请求反代到 compose 内的 backend:8000
CMD ["nginx", "-g", "daemon off;"]
