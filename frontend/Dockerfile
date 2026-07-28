# Contexto de build: a pasta frontend/.
FROM node:24-alpine AS build

WORKDIR /app

# package.json + lockfile primeiro: o layer de dependências só reconstrói quando eles mudam.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

FROM nginx:1.29-alpine AS runtime

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
