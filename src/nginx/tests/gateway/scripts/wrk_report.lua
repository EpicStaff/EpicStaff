-- Prints request count, errors and latency percentiles (wrk reports microseconds).
done = function(summary, latency, requests)
  local errors = summary.errors
  io.write(string.format("requests=%d seconds=%.1f errors connect=%d read=%d write=%d timeout=%d non2xx=%d\n",
    summary.requests, summary.duration / 1e6, errors.connect, errors.read, errors.write, errors.timeout, errors.status))
  io.write(string.format("p50_ms=%.3f p90_ms=%.3f p99_ms=%.3f p999_ms=%.3f max_ms=%.3f\n",
    latency:percentile(50) / 1000, latency:percentile(90) / 1000, latency:percentile(99) / 1000,
    latency:percentile(99.9) / 1000, latency.max / 1000))
end
