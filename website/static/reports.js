const COLORS = {
    overall:     "#6366f1",
    clarity:     "#8b5cf6",
    confidence:  "#10b981",
    conciseness: "#f59e0b",
    technical:   "#ef4444",
};

const KEYS = Object.keys(COLORS);

const layout = {
    paper_bgcolor: "#ffffff",
    plot_bgcolor:  "#ffffff",
    font: { color: "#475569", family: "inherit" },
    margin: { t: 20, r: 30, b: 80, l: 50 },
    autosize: true,
    yaxis: {
        range: [0, 11],
        tickvals: [0, 2, 4, 6, 8, 10],
        gridcolor: "#f1f5f9",
        linecolor: "#e2e8f0",
        zerolinecolor: "#e2e8f0",
        fixedrange: true,
        tickfont: { color: "#94a3b8", size: 11 },
        title: { text: "Score /10", font: { size: 12, color: "#94a3b8" } }
    },
    xaxis: {
        gridcolor: "rgba(0,0,0,0)",
        linecolor: "#e2e8f0",
        fixedrange: true,
        tickangle: -30,
        tickfont: { color: "#64748b", size: 11 },
    },
    showlegend: false,
    hovermode: "x unified",
    hoverlabel: {
        bgcolor: "#1e293b",
        bordercolor: "rgba(255,255,255,0.1)",
        font: { color: "#fff", size: 13 }
    }
};
function buildTraces(sessions) {
    const labels = sessions.map((s, idx) => {
        const d = new Date(s.date + "T00:00:00");
        return `S${idx + 1} · ${d.toLocaleDateString("en-US", { month: "short", day: "numeric" })}`;
    });

    return KEYS.map(key => ({
        x: labels,
        y: sessions.map(s => s[key] ?? 0),
        type: "scatter",
        mode: "lines+markers",
        name: key.charAt(0).toUpperCase() + key.slice(1),
        line: {
            color: COLORS[key],
            width: key === "overall" ? 4 : 2,
            shape: "spline",
            smoothing: 1.3,
        },
        marker: {
            color: COLORS[key],
            size: key === "overall" ? 10 : 7,
            line: { color: "#fff", width: 2 }
        },
        fill: key === "overall" ? "tozeroy" : "none",
        fillcolor: "rgba(99,102,241,0.08)",
        // Initial visibility: only overall is 'true', others are 'legendonly' (hidden but toggleable)
        visible: key === "overall" ? true : "legendonly",
        hovertemplate: `%{y}/10<extra></extra>`,
    }));
}

document.addEventListener("DOMContentLoaded", async () => {
    const chartDiv = document.getElementById("scoreChart");
    try {
        const res = await fetch("/reports-data");
        const json = await res.json();

        if (json.error || !json.sessions || json.sessions.length === 0) {
            chartDiv.innerHTML = `<div class="text-center p-5"><p class="text-muted">No data available yet.</p></div>`;
            return;
        }

        // Update Stats
        document.getElementById("stat-streak").innerText = json.streak ?? 0;
        document.getElementById("stat-longest").innerText = json.longest_streak ?? 0;
        document.getElementById("stat-sessions").innerText = json.total_sessions ?? 0;
        const bestOverall = Math.max(...json.sessions.map(s => s.overall ?? 0));
        document.getElementById("stat-best").innerText = bestOverall + "/10";

        // Build and Render Chart
        const traces = buildTraces(json.sessions);
        await Plotly.newPlot(chartDiv, traces, layout, { responsive: true, displayModeBar: false });

        // Toggle logic
        const visible = new Set(["overall"]);
        document.querySelectorAll(".toggle-btn").forEach(btn => {
            btn.addEventListener("click", () => {
                const key = btn.getAttribute("data-key");
                
                if (visible.has(key)) {
                    if (visible.size === 1) return; // Keep at least one visible
                    visible.delete(key);
                    btn.classList.remove("active");
                } else {
                    visible.add(key);
                    btn.classList.add("active");
                }

                KEYS.forEach((k, i) => {
                    const isVisible = visible.has(k);
                    Plotly.restyle(chartDiv, { visible: isVisible ? true : "legendonly" }, [i]);
                });
            });
        });

    } catch (err) {
        console.error(err);
        chartDiv.innerHTML = '<p class="text-center mt-5">Error loading chart.</p>';
    }
});