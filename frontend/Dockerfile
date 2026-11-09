# Stage 1: 构建 React 应用
FROM node:20-alpine AS build

WORKDIR /app

# 先复制依赖声明，利用 Docker 缓存层
COPY package*.json ./
RUN npm ci

# 复制源码和构建配置
COPY index.html ./
COPY vite.config.js ./
COPY tailwind.config.js ./
COPY postcss.config.js ./
COPY src/ ./src/

RUN npm run build

# Stage 2: 生产环境 nginx 服务
FROM nginx:alpine AS production

# 用自定义配置覆盖默认配置
RUN rm /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/conf.d/default.conf

# 从构建阶段复制产物
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
