FROM golang:1.22-alpine AS build
WORKDIR /src
COPY soak/soak-monitor.go .
RUN go build -o /soak-monitor soak-monitor.go

FROM alpine:latest
COPY --from=build /soak-monitor /soak-monitor
EXPOSE 8082
CMD ["/soak-monitor"]
