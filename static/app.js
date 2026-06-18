/**
 * MoodTune – Frontend Logic
 * Handles mood analysis requests, UI transitions, usage limits,
 * mood history (localStorage), and background particles.
 */

(function () {
    "use strict";

    // ── Constants ──────────────────────────────────────────────────
    const API_URL = "/analyze";
    const FREE_LIMIT = 5;
    const STORAGE_KEY = "moodtune_history";
    const USAGE_KEY = "moodtune_usage";
    const PREMIUM_KEY = "moodtune_premium";

    // ── DOM References ────────────────────────────────────────────
    const $ = (sel) => document.querySelector(sel);
    const $$ = (sel) => document.querySelectorAll(sel);

    const moodInput = $("#moodInput");
    const charCount = $("#charCount");
    const analyzeBtn = $("#analyzeBtn");
    const usageCounter = $("#usageCounter");
    const heroSection = $("#heroSection");
    const loadingSection = $("#loadingSection");
    const resultsSection = $("#resultsSection");
    const moodDisplay = $("#moodDisplay");
    const playlistSections = $("#playlistSections");
    const tryAgainBtn = $("#tryAgainBtn");
    const toast = $("#toast");
    const toastIcon = $("#toastIcon");
    const toastText = $("#toastText");
    const upgradeBtn = $("#upgradeBtn");

    // History view
    const historyTimeline = $("#historyTimeline");
    const emptyHistory = $("#emptyHistory");
    const moodStats = $("#moodStats");
    const clearHistoryBtn = $("#clearHistoryBtn");

    // Nav
    const navBtns = $$(".nav-btn");
    const views = $$(".view");

    // Quick mood chips
    const moodChips = $$(".mood-chip");

    // ── State ──────────────────────────────────────────────────────
    let isPremium = JSON.parse(localStorage.getItem(PREMIUM_KEY) || "false");

    // ── Background Particles ──────────────────────────────────────
    function initParticles() {
        const container = $("#bgParticles");
        const colors = ["#7c5cfc", "#e84393", "#fd79a8", "#a29bfe", "#6c5ce7"];
        const count = 25;

        for (let i = 0; i < count; i++) {
            const p = document.createElement("div");
            p.classList.add("particle");
            const size = Math.random() * 4 + 2;
            const color = colors[Math.floor(Math.random() * colors.length)];
            const left = Math.random() * 100;
            const duration = Math.random() * 15 + 10;
            const delay = Math.random() * 15;

            p.style.cssText = `
                width: ${size}px;
                height: ${size}px;
                background: ${color};
                left: ${left}%;
                animation-duration: ${duration}s;
                animation-delay: ${delay}s;
                box-shadow: 0 0 ${size * 3}px ${color};
            `;
            container.appendChild(p);
        }
    }

    // ── Navigation ────────────────────────────────────────────────
    function switchView(viewId) {
        views.forEach((v) => v.classList.remove("active"));
        navBtns.forEach((b) => b.classList.remove("active"));

        const target = $(`#view${capitalize(viewId)}`);
        const btn = $(`[data-view="${viewId}"]`);
        if (target) target.classList.add("active");
        if (btn) btn.classList.add("active");

        if (viewId === "history") renderHistory();
    }

    navBtns.forEach((btn) => {
        btn.addEventListener("click", () => {
            switchView(btn.dataset.view);
        });
    });

    // Logo click → go home
    $("#logo").addEventListener("click", () => {
        switchView("home");
        showHero();
    });

    // ── Character Counter ─────────────────────────────────────────
    moodInput.addEventListener("input", () => {
        charCount.textContent = `${moodInput.value.length} / 500`;
    });

    // ── Usage Tracking ────────────────────────────────────────────
    function getUsageToday() {
        let data = JSON.parse(localStorage.getItem(USAGE_KEY) || "{}");
        if (typeof data !== "object" || data === null || Array.isArray(data)) {
            data = {};
            localStorage.setItem(USAGE_KEY, JSON.stringify(data));
        }
        const today = new Date().toISOString().slice(0, 10);
        return { count: data[today] || 0, today };
    }

    function incrementUsage() {
        let data = JSON.parse(localStorage.getItem(USAGE_KEY) || "{}");
        if (typeof data !== "object" || data === null || Array.isArray(data)) {
            data = {};
        }
        const today = new Date().toISOString().slice(0, 10);
        data[today] = (data[today] || 0) + 1;
        localStorage.setItem(USAGE_KEY, JSON.stringify(data));
    }

    function updateUsageDisplay() {
        const { count } = getUsageToday();
        if (isPremium) {
            usageCounter.textContent = "✨ Premium – Unlimited analyses";
            usageCounter.style.color = "#a78bfa";
            return;
        }
        const remaining = FREE_LIMIT - count;
        if (remaining <= 0) {
            usageCounter.textContent = `No free analyses left today. Upgrade to Premium!`;
            usageCounter.style.color = "#d63031";
            analyzeBtn.disabled = true;
        } else {
            usageCounter.textContent = `${remaining} free ${remaining === 1 ? "analysis" : "analyses"} remaining today`;
            usageCounter.style.color = "";
            analyzeBtn.disabled = false;
        }
    }

    // ── Quick Mood Chips ──────────────────────────────────────────
    moodChips.forEach((chip) => {
        chip.addEventListener("click", () => {
            moodInput.value = chip.dataset.text;
            charCount.textContent = `${moodInput.value.length} / 500`;
            moodInput.focus();
        });
    });

    // ── Analyze Mood ──────────────────────────────────────────────
    analyzeBtn.addEventListener("click", analyzeMood);

    // Allow Ctrl+Enter to submit
    moodInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
            e.preventDefault();
            analyzeMood();
        }
    });

    async function analyzeMood() {
        const text = moodInput.value.trim();
        if (!text) {
            showToast("⚠️", "Please type how you're feeling first!");
            return;
        }

        // Check usage limit
        if (!isPremium) {
            const { count } = getUsageToday();
            if (count >= FREE_LIMIT) {
                showToast("🔒", "Daily limit reached. Upgrade to Premium!");
                return;
            }
        }

        // Show loading
        heroSection.classList.add("hidden");
        resultsSection.classList.add("hidden");
        loadingSection.classList.remove("hidden");
        analyzeBtn.disabled = true;

        try {
            const res = await fetch(API_URL, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ text }),
            });

            if (!res.ok) throw new Error("API error");

            const data = await res.json();

            // Track usage
            incrementUsage();

            // Save to history
            const primaryMood = data.moods[0];
            const allMoodNames = data.moods.map(m => m.mood);
            saveHistory(text, allMoodNames, primaryMood.data.emoji);

            // Show results
            showResults(data.moods);

        } catch (err) {
            console.error("Analyze error:", err);
            showToast("❌", "Something went wrong. Please try again.");
            showHero();
        } finally {
            analyzeBtn.disabled = false;
            updateUsageDisplay();
        }
    }

    // ── Show/Hide Sections ────────────────────────────────────────
    function showHero() {
        loadingSection.classList.add("hidden");
        resultsSection.classList.add("hidden");
        heroSection.classList.remove("hidden");
    }

    function showResults(moods) {
        loadingSection.classList.add("hidden");
        heroSection.classList.add("hidden");
        resultsSection.classList.remove("hidden");

        // Clear previous results
        moodDisplay.innerHTML = "";
        playlistSections.innerHTML = "";

        const isMixed = moods.length > 1;

        // ── Build mood display ─────────────────────────────────────
        if (isMixed) {
            const badgesHtml = moods.map((m) => {
                const pct = Math.round((m.confidence || 1) * 100);
                return `
                <div class="mood-badge" style="background: ${m.data.gradient}; box-shadow: 0 8px 32px ${m.data.color}55, inset 0 1px 0 rgba(255,255,255,0.2);">
                    <div class="mood-badge-top">
                        <span class="mood-badge-emoji">${m.data.emoji}</span>
                        <span class="mood-badge-label">${capitalize(m.mood)}</span>
                    </div>
                    <div style="width:100%;height:3px;background:rgba(255,255,255,0.2);border-radius:2px;margin-top:4px;">
                        <div style="width:${pct}%;height:100%;background:rgba(255,255,255,0.9);border-radius:2px;transition:width 0.8s cubic-bezier(0.16,1,0.3,1);box-shadow:0 0 6px rgba(255,255,255,0.5);"></div>
                    </div>
                    <span style="font-size:11px;color:rgba(255,255,255,0.8);font-weight:600;letter-spacing:0.04em;">${pct}% match</span>
                </div>
            `;
            }).join('<span class="mood-badge-plus">+</span>');

            moodDisplay.innerHTML = `
                <div class="mixed-mood-header">
                    <h2 class="mixed-mood-title">
                        We detected <span class="gradient-text">multiple moods</span>
                    </h2>
                    <p class="mixed-mood-subtitle">
                        Here's music for every side of how you feel
                    </p>
                    <div class="mood-badge-row">${badgesHtml}</div>
                </div>
            `;
        } else {
            const m = moods[0];
            moodDisplay.innerHTML = `
                <div class="mood-card" style="background: ${m.data.gradient}, var(--bg-card)">
                    <div class="mood-card-emoji" style="text-shadow: 0 0 30px ${m.data.color}40">${m.data.emoji}</div>
                    <h2 class="mood-card-title">Your mood: <span style="color: ${m.data.color}">${capitalize(m.mood)}</span></h2>
                    <p class="mood-card-message">${m.data.message}</p>
                </div>
            `;
        }

        // ── Build playlist sections ────────────────────────────────
        // Song counts by confidence rank: primary → 5, secondary → 3, tertiary → 2
        const SONG_COUNTS = [5, 3, 2];
        moods.forEach((m, idx) => {
            const songsToShow = isMixed
                ? m.data.playlists.slice(0, SONG_COUNTS[idx] !== undefined ? SONG_COUNTS[idx] : 2)
                : m.data.playlists;

            const section = document.createElement("div");
            section.classList.add("mood-playlist-section");

            if (isMixed) {
                const header = document.createElement("div");
                header.classList.add("mood-section-header");
                header.innerHTML = `
                    <span class="mood-section-emoji">${m.data.emoji}</span>
                    <h3 class="mood-section-title" style="color: ${m.data.color}">
                        For your ${capitalize(m.mood)} side
                    </h3>
                `;
                section.appendChild(header);
            }

            const grid = document.createElement("div");
            grid.classList.add("playlist-grid");

            songsToShow.forEach((song) => {
                const card = document.createElement("a");
                card.classList.add("song-card");
                card.href = song.url;
                card.target = "_blank";
                card.rel = "noopener noreferrer";
                card.innerHTML = `
                    <div class="song-cover">${song.cover}</div>
                    <div class="song-info">
                        <div class="song-title">${escapeHtml(song.title)}</div>
                        <div class="song-artist">${escapeHtml(song.artist)}</div>
                        <div class="song-duration">${song.duration}</div>
                    </div>
                `;
                grid.appendChild(card);
            });

            section.appendChild(grid);
            playlistSections.appendChild(section);
        });
    }

    tryAgainBtn.addEventListener("click", () => {
        moodInput.value = "";
        charCount.textContent = "0 / 500";
        showHero();
        moodInput.focus();
        window.scrollTo({ top: 0, behavior: "smooth" });
    });

    // ── Mood History ──────────────────────────────────────────────
    function getHistory() {
        return JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
    }

    function saveHistory(text, moods, emoji) {
        const history = getHistory();
        history.unshift({
            text,
            moods: moods,          // array of mood names
            mood: moods[0],        // primary mood (backward compat)
            emoji,
            timestamp: Date.now(),
        });
        // Keep last 50 entries
        if (history.length > 50) history.length = 50;
        localStorage.setItem(STORAGE_KEY, JSON.stringify(history));
    }

    function renderHistory() {
        const history = getHistory();
        historyTimeline.innerHTML = "";

        if (history.length === 0) {
            historyTimeline.innerHTML =
                '<p class="empty-state">No mood entries yet. Go analyze your first mood!</p>';
            moodStats.innerHTML = "";
            return;
        }

        // Stats – count each mood separately for multi-mood entries
        const counts = {};
        history.forEach((entry) => {
            const entryMoods = entry.moods || [entry.mood];
            entryMoods.forEach((m) => {
                counts[m] = (counts[m] || 0) + 1;
            });
        });

        moodStats.innerHTML = Object.entries(counts)
            .sort((a, b) => b[1] - a[1])
            .map(
                ([mood, count]) => `
                <div class="stat-chip">
                    ${moodEmojiMap(mood)} ${capitalize(mood)}
                    <span class="stat-count">${count}</span>
                </div>
            `
            )
            .join("");

        // Timeline
        history.forEach((entry) => {
            const entryMoods = entry.moods || [entry.mood];
            const moodNames = entryMoods.map((m) => capitalize(m)).join(" + ");
            const div = document.createElement("div");
            div.classList.add("history-entry");
            div.innerHTML = `
                <div class="history-emoji">${entry.emoji}</div>
                <div class="history-info">
                    <div class="history-mood">${moodNames}</div>
                    <div class="history-text">${escapeHtml(entry.text)}</div>
                </div>
                <div class="history-time">${timeAgo(entry.timestamp)}</div>
            `;
            historyTimeline.appendChild(div);
        });
    }

    clearHistoryBtn.addEventListener("click", () => {
        localStorage.removeItem(STORAGE_KEY);
        renderHistory();
        showToast("🗑️", "Mood history cleared.");
    });

    // ── Premium Toggle ─────────────────────────────────────────────
    upgradeBtn.addEventListener("click", async () => {
        isPremium = !isPremium;
        localStorage.setItem(PREMIUM_KEY, JSON.stringify(isPremium));

        // Sync premium status to Flask server so notifier.py can read it
        try {
            await fetch("/premium", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ premium: isPremium }),
            });
        } catch (e) {
            console.warn("[MoodTune] Could not sync premium status to server:", e);
        }

        updatePremiumUI();
        updateUsageDisplay();
        showToast(
            isPremium ? "✨" : "ℹ️",
            isPremium
                ? "Premium plan activated!"
                : "Switched to Free plan."
        );
    });

    function updatePremiumUI() {
        upgradeBtn.textContent = isPremium
            ? "✓ Premium Active (Click to Deactivate)"
            : "Upgrade to Premium";
    }

    // ── Toast Notifications ───────────────────────────────────────
    let toastTimer = null;
    function showToast(icon, message) {
        toastIcon.textContent = icon;
        toastText.textContent = message;
        toast.classList.remove("hidden");

        // Force reflow for animation
        void toast.offsetWidth;
        toast.classList.add("show");

        clearTimeout(toastTimer);
        toastTimer = setTimeout(() => {
            toast.classList.remove("show");
            setTimeout(() => toast.classList.add("hidden"), 300);
        }, 3000);
    }

    // ── Helpers ───────────────────────────────────────────────────
    function capitalize(str) {
        return str.charAt(0).toUpperCase() + str.slice(1);
    }

    function escapeHtml(str) {
        const div = document.createElement("div");
        div.textContent = str;
        return div.innerHTML;
    }

    function timeAgo(ts) {
        const diff = Date.now() - ts;
        const mins = Math.floor(diff / 60000);
        if (mins < 1) return "Just now";
        if (mins < 60) return `${mins}m ago`;
        const hrs = Math.floor(mins / 60);
        if (hrs < 24) return `${hrs}h ago`;
        const days = Math.floor(hrs / 24);
        return `${days}d ago`;
    }

    function moodEmojiMap(mood) {
        const map = {
            happy: "😊", sad: "😢", stressed: "😰", calm: "😌",
            energetic: "⚡", romantic: "❤️", angry: "😤", focused: "🎯",
        };
        return map[mood] || "🎵";
    }

    // ── Init ──────────────────────────────────────────────────────
    initParticles();
    updateUsageDisplay();
    updatePremiumUI();

    // Sync the stored premium status to the server on every page load.
    // This ensures notifier.py sees the correct state even after a browser refresh.
    (async function syncPremiumOnLoad() {
        try {
            await fetch("/premium", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ premium: isPremium }),
            });
        } catch (e) { /* server may not be ready yet — silently ignore */ }
    })();

})();
