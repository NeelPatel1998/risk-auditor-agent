## Multi-stage: build React SPA, then nginx reverse-proxy + static UI (:8080)
## Build: from repo root `docker compose build gateway`

FROM node:20-alpine AS frontend-build
WORKDIR /fe
COPY package.json package-lock.json ./
# npm ci can fail in Linux images when lock was produced on Windows with optional deps omitted — install resolves @emnapi/* for this platform
RUN npm install --no-audit --no-fund
COPY . ./
# Same-origin API when UI is served from gateway; override for split hosts if needed
ARG VITE_API_URL=
ENV VITE_API_URL=${VITE_API_URL}
RUN npm run build

FROM nginx:alpine
COPY nginx-gateway.conf /etc/nginx/conf.d/default.conf
COPY --from=frontend-build /fe/dist /usr/share/nginx/html

