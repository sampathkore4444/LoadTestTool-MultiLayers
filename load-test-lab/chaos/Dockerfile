FROM golang:1.22-alpine AS build
WORKDIR /src
COPY chaos/chaos-agent.go .
RUN go build -o /chaos-agent chaos-agent.go

FROM alpine:latest
RUN apk --no-cache add iptables iproute2 tc
COPY --from=build /chaos-agent /chaos-agent
EXPOSE 8081
CMD ["/chaos-agent"]
