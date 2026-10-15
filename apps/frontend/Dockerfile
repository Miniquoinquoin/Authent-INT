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
# Vite bakes VITE_* into the bundle at build time: the auth-server URL is part of the image.
# Override with `--build-arg VITE_AUTH_URL=…` (compose: build.args).
ARG VITE_AUTH_URL=https://auth.authentint.localhost
ARG VITE_IMPOTS_URL=https://impots.authentint.localhost
ARG VITE_CADASTRE_URL=https://cadastre.authentint.localhost
ENV VITE_AUTH_URL=${VITE_AUTH_URL} VITE_IMPOTS_URL=${VITE_IMPOTS_URL} VITE_CADASTRE_URL=${VITE_CADASTRE_URL}
COPY . .
RUN npm run build

FROM nginx:alpine AS serve
ARG VITE_AUTH_URL=https://auth.authentint.localhost
ARG VITE_IMPOTS_URL=https://impots.authentint.localhost
ARG VITE_CADASTRE_URL=https://cadastre.authentint.localhost
COPY nginx.conf.template /tmp/default.conf.template
# Rendered and checked now, not at start-up: a broken config fails the build, not the deploy
RUN AUTH_ORIGIN="${VITE_AUTH_URL}" IMPOTS_ORIGIN="${VITE_IMPOTS_URL}" CADASTRE_ORIGIN="${VITE_CADASTRE_URL}" \
    envsubst '${AUTH_ORIGIN} ${IMPOTS_ORIGIN} ${CADASTRE_ORIGIN}' < /tmp/default.conf.template > /etc/nginx/conf.d/default.conf \
    && rm /tmp/default.conf.template \
    && nginx -t
COPY --from=build /app/dist /usr/share/nginx/html
