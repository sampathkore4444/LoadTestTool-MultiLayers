FROM golang:1.22-alpine AS builder
WORKDIR /app
COPY chaos-agent.go .
RUN CGO_ENABLED=0 GOOS=linux go build -o /chaos-agent .

FROM alpine:latest
RUN apk add --no-cache iptables iproute2 docker-cli curl
COPY --from=builder /chaos-agent /chaos-agent
EXPOSE 8080
ENTRYPOINT ["/chaos-agent"]