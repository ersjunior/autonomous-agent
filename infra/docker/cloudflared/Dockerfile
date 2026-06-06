# Wrapper Alpine: imagem oficial cloudflared é binário-only (sem shell para entrypoint).
FROM cloudflare/cloudflared:latest AS cloudflared-bin

FROM alpine:3.20
RUN apk add --no-cache ca-certificates grep
COPY --from=cloudflared-bin /usr/local/bin/cloudflared /usr/local/bin/cloudflared
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/bin/sh", "/entrypoint.sh"]
