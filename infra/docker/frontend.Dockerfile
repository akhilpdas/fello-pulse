# Web image: build the UI, serve it with nginx, proxy /api to the API (same-origin, so no CORS).
# UNVERIFIED: this file has not been built -- Docker is not installed on the machine it was written on.
FROM node:22-alpine AS build
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM nginxinc/nginx-unprivileged:alpine
COPY infra/docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /web/dist /usr/share/nginx/html
EXPOSE 8080
