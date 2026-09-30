# syntax=docker/dockerfile:1

FROM node:22-alpine AS deps
WORKDIR /app
COPY package*.json ./
RUN --mount=type=cache,target=/root/.npm npm ci

# Dev Stage
FROM deps AS dev
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "80"]

# Normal Stage
FROM deps AS build
COPY . .
RUN npm run build

FROM nginx:alpine AS serve
COPY --from=build /app/dist /usr/share/nginx/html
