# Todo via Docker — no hace falta Go (ni mise) en la máquina.

build:            ## binario linux/amd64 → native/conga
	docker buildx build --platform linux/amd64 --target artifacts -o native/ native/
	mv -f native/conga-linux-amd64 native/conga

arm64:            ## binario linux/arm64 (HA / Raspberry Pi 64) → native/conga-linux-arm64
	docker buildx build --platform linux/arm64 --target artifacts -o native/ native/

test: build       ## smoke test offline: decode los mapas del repo
	./native/conga decode maps/*.bin >/dev/null && echo OK

image:            ## imagen CLI ejecutable: docker run --rm conga-cli status
	docker build -t conga-cli native/

clean:
	rm -f native/conga native/conga-linux-*

.PHONY: build arm64 test image clean
