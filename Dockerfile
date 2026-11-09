# Bitsreef deployment image (VLESS+WS, TLS terminated at Bitsreef edge)
# Reuses routeA wrapper server.py: listens on $PORT (platform-given, default 8080),
# serves /sub, reverse-proxies WS to xray on 127.0.0.1:10000.
# Bitsreef: Add Service default Exposed Port 8080; set UUID/WS_PATH via env vars.
FROM alpine:3.20 AS xray-dl
ARG XRAY_VERSION=v26.10.31
RUN apk add --no-cache curl ca-certificates unzip
RUN curl -fsSL -o /tmp/xray.zip \
      "https://github.com/XTLS/Xray-core/releases/download/${XRAY_VERSION}/Xray-linux-64.zip" \
    && unzip -o /tmp/xray.zip -d /tmp/xray \
    && chmod +x /tmp/xray/xray \
    && /tmp/xray/xray version
FROM alpine:3.20
RUN apk add --no-cache ca-certificates python3
COPY --from=xray-dl /tmp/xray/xray /app/xray
COPY server.py /app/server.py
WORKDIR /app
ENV PORT=8080 \
    WS_PATH=/ws \
    SUB_PATH=/sub \
    NODE_NAME=v2rayn-node-shiper
EXPOSE 8080
CMD ["python3", "server.py"]
