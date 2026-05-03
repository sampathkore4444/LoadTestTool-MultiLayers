package main

import (
    "fmt"
    "log"
    "net/http"
    "time"
)

func queryPrometheus(query string) float64 {
    url := fmt.Sprintf("http://prometheus:9090/api/v1/query?query=%s", query)
    resp, err := http.Get(url)
    if err != nil { return 0 }
    defer resp.Body.Close()
    var v struct {
        Data struct{ Result []struct{ Value []interface{} } } `json:"data"`
    }
    if err := json.NewDecoder(resp.Body).Decode(&v); err != nil { return 0 }
    if len(v.Data.Result)==0 || len(v.Data.Result[0].Value)<2 { return 0 }
    if n, ok := v.Data.Result[0].Value[1].(float64); ok { return n }
    return 0
}

func soakMonitor() {
    // memory leak detection: RSS growth over 30m
    var lastRss float64
    for {
        time.Sleep(5 * time.Minute)
        rss := queryPrometheus(processResidentMemoryBytes)
        if rss > lastRss*1.5 && lastRss>0 {
            log.Printf("MEMORY LEAK DETECTED: %.0f -> %.0f", lastRss, rss)
            // webhook or flag
        }
        lastRss = rss
        // regression: p99 latency increase > 2x baseline
        p99 := queryPrometheus(histogramQuantile(0.99, "backend_api_duration_seconds"))
        baseline := 100.0 // ms, configurable
        if p99 > baseline*2 {
            log.Printf("REGRESSION: p99=%.0fms > %.0fms", p99, baseline*2)
        }
    }
}

func main() {
    log.Println("soak-monitor starting")
    soakMonitor()
}
