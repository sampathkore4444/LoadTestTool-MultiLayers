package main

import (
    "encoding/json"
    "fmt"
    "log"
    "net/http"
    "os"
    "os/exec"
    "sync"
    "time"
)

type Fault struct {
    ID      string    `json:"id"`
    Type    string    `json:"type"`    // pod-kill, latency, db-disconnect, cpu-stress
    Target  string    `json:"target"`  // service name or pod selector
    Value   string    `json:"value"`   // e.g. "200ms", "30s", "50%"
    Duration string   `json:"duration"`
}

type Event struct {
    Timestamp time.Time `json:"timestamp"`
    FaultID   string    `json:"fault_id"`
    Type      string    `json:"type"`
    Target    string    `json:"target"`
    Action    string    `json:"action"`
    Result    string    `json:"result"`
}

var (
    events   []Event
    mu       sync.Mutex
    timeline = "/data/timeline.json"
)

func injectHandler(w http.ResponseWriter, r *http.Request) {
    var f Fault
    if err := json.NewDecoder(r.Body).Decode(&f); err != nil {
        http.Error(w, err.Error(), 400); return
    }
    f.ID = fmt.Sprintf("f-%d", time.Now().UnixNano())
    go executeFault(f)
    w.Header().Set("Content-Type", "application/json")
    json.NewEncoder(w).Encode(map[string]string{"id": f.ID, "status": "injecting"})
}

func executeFault(f Fault) {
    var result string
    switch f.Type {
    case "pod-kill":
        cmd := exec.Command("sh", "-c", fmt.Sprintf("kubectl delete pod -l app=%s --grace-period=0 --force 2>&1 || true", f.Target))
        out, _ := cmd.CombinedOutput()
        result = string(out)
    case "latency":
        // Use tc via nsenter or target container
        cmd := exec.Command("sh", "-c", fmt.Sprintf("tc qdisc add dev eth0 root netem delay %s 2>&1 || true", f.Value))
        out, _ := cmd.CombinedOutput()
        result = string(out)
        if f.Duration != "" {
            d, _ := time.ParseDuration(f.Duration)
            time.AfterFunc(d, func() {
                exec.Command("sh", "-c", "tc qdisc del dev eth0 root 2>&1 || true").Run()
            })
        }
    case "db-disconnect":
        // Block traffic to database container
        exec.Command("sh", "-c", "iptables -A OUTPUT -d database -j DROP 2>&1 || true").Run()
        if f.Duration != "" {
            d, _ := time.ParseDuration(f.Duration)
            time.AfterFunc(d, func() {
                exec.Command("sh", "-c", "iptables -D OUTPUT -d database -j DROP 2>&1 || true").Run()
            })
        }
        result = "database traffic blocked"
    case "cpu-stress":
        exec.Command("sh", "-c", "dd if=/dev/urandom of=/dev/null bs=1M count=10000 2>&1 | head -5 &").Run()
        result = "cpu stress started"
    default:
        result = "unknown fault type"
    }
    recordEvent(f.ID, f.Type, f.Target, "injected", result)
}

func recordEvent(fid, typ, target, action, result string) {
    mu.Lock()
    defer mu.Unlock()
    ev := Event{Timestamp: time.Now(), FaultID: fid, Type: typ, Target: target, Action: action, Result: result}
    events = append(events, ev)
    saveTimeline()
}

func saveTimeline() {
    f, _ := os.Create(timeline)
    json.NewEncoder(f).Encode(events)
    f.Close()
}

func listHandler(w http.ResponseWriter, r *http.Request) {
    mu.Lock()
    defer mu.Unlock()
    w.Header().Set("Content-Type", "application/json")
    json.NewEncoder(w).Encode(events)
}

func healthHandler(w http.ResponseWriter, r *http.Request) {
    w.Write([]byte("ok"))
}

func main() {
    os.MkdirAll("/data", 0755)
    http.HandleFunc("/inject", injectHandler)
    http.HandleFunc("/list", listHandler)
    http.HandleFunc("/timeline", listHandler)
    http.HandleFunc("/health", healthHandler)
    log.Println("chaos-agent listening on :8081")
    log.Fatal(http.ListenAndServe(":8081", nil))
}
