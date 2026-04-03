document.addEventListener("DOMContentLoaded", async () => {
    try {
        const res  = await fetch("/evaluate-latest");
        const json = await res.json();

        // ✅ Show the actual error so you can debug
        if (json.error) {
            document.getElementById("feedback-text").innerText =
                "Error: " + json.error;
            console.error("Evaluate error:", json.error);
            return;
        }

        const evalData = json.evaluation;

        if (!evalData) {
            document.getElementById("feedback-text").innerText =
                "No evaluation data returned.";
            return;
        }

        console.log("evalData received:", evalData); // ← check browser console

        document.querySelectorAll(".ring-card").forEach(ring => {
            const key   = ring.getAttribute("data-key");
            const value = evalData[key];

            console.log(`Key: ${key}, Value: ${value}`); // ← verify each key

            if (value === undefined || value === null) return;

            const circle       = ring.querySelector(".progress");
            const scoreText    = ring.querySelector(".score");
            const radius       = circle.r.baseVal.value;
            const circumference = 2 * Math.PI * radius;

            circle.style.strokeDasharray  = circumference;
            circle.style.strokeDashoffset = circumference; // start empty

            setTimeout(() => {
                circle.style.strokeDashoffset = circumference * (1 - value / 10);
                scoreText.innerText = value + "/10";
            }, 200);
        });

        if (evalData.feedback) {
            document.getElementById("feedback-text").innerText = evalData.feedback;
        }

    } catch (err) {
        console.error("Evaluation fetch failed:", err);
        document.getElementById("feedback-text").innerText =
            "Failed to load evaluation.";
    }
});