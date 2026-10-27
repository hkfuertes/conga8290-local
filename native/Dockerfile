# Cross-compiles for ARG TARGETARCH (amd64/arm64, set automatically by buildx):
#   docker buildx build --platform linux/arm64 --target artifacts -o . .
FROM golang:1.27-alpine AS build
ARG TARGETARCH
WORKDIR /src
COPY go.mod ./
COPY *.go ./
RUN CGO_ENABLED=0 go build -ldflags='-s -w' -o /out/conga-linux-${TARGETARCH} .

# Artifacts-only stage: what --target artifacts -o exports (just the binary).
FROM scratch AS artifacts
ARG TARGETARCH
COPY --from=build /out/conga-linux-${TARGETARCH} /conga-linux-${TARGETARCH}

# Runnable CLI image (mount private/ for config, maps/ for output):
#   docker run --rm -v $PWD/private:/private -v $PWD/maps:/maps conga-cli status
FROM scratch
ARG TARGETARCH
COPY --from=artifacts /conga-linux-${TARGETARCH} /conga
ENTRYPOINT ["/conga"]
