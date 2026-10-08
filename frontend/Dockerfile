FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

# Unprivileged nginx: runs as a non-root user and listens on 8080
FROM nginxinc/nginx-unprivileged:1.31-alpine
LABEL org.opencontainers.image.source="https://github.com/Jdilsham/AI-Kubernetes-Agent" \
      org.opencontainers.image.description="AI Kubernetes Agent frontend" \
      org.opencontainers.image.licenses="MIT"
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
ENV BACKEND_URL=http://backend:9000
EXPOSE 8080
