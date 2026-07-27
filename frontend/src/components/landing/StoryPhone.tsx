"use client";

import { useEffect, useRef, useState } from "react";
import { fmtGap, fmtPence, type LandingStory } from "@/lib/landingStory";
import { drawStoryChart } from "@/lib/storyChart";

/**
 * The story of the week as a phone-shaped player — the 34-second Shorts
 * storyboard, tightened to ~14s and driven off live data:
 *
 *   1. the 07:00 wire scrolling past, counting up to everything that landed
 *   2. the funnel: what landed -> what survived the filter -> what scored 80+
 *   3. the winning announcement's score card
 *   4. the price reaction, chart drawing in and the gap counter rolling up
 *
 * It rests on scene 4. Purely presentational — `aria-hidden` and skippable — so
 * nothing the visitor needs is stated here alone: the surrounding signup card
 * carries the offer, and /rns carries the announcements themselves.
 *
 * Scene text is sized in container-query units so the whole thing scales with
 * the frame, exactly as the storyboard did inside its 9:16 stage.
 */

// Scene end times. Paced for reading rather than for a Shorts feed: the two
// text-heavy scenes (the funnel and the score card's thesis) get the most room,
// and every internal beat is a fraction of its scene, so they scale with these.
const S1 = 4400; // wire
const S2 = 9200; // funnel
const S3 = 15400; // score card
const S4 = 21800; // result — then it rests here
const FADE = 600;

function clamp01(v: number) {
  return v < 0 ? 0 : v > 1 ? 1 : v;
}
function seg(p: number, a: number, b: number) {
  return clamp01((p - a) / (b - a));
}
function easeOut(t: number) {
  return 1 - Math.pow(1 - t, 3);
}

export default function StoryPhone({ story }: { story: LandingStory }) {
  const [mounted, setMounted] = useState(false);
  const frameRef = useRef<HTMLDivElement | null>(null);
  const sceneRefs = [
    useRef<HTMLDivElement | null>(null),
    useRef<HTMLDivElement | null>(null),
    useRef<HTMLDivElement | null>(null),
    useRef<HTMLDivElement | null>(null),
  ];
  const trackRef = useRef<HTMLDivElement | null>(null);
  const countRef = useRef<HTMLDivElement | null>(null);
  const clockRef = useRef<HTMLDivElement | null>(null);
  const funnelRefs = [
    useRef<HTMLDivElement | null>(null),
    useRef<HTMLDivElement | null>(null),
    useRef<HTMLDivElement | null>(null),
  ];
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const toRef = useRef<HTMLSpanElement | null>(null);
  const pctRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => setMounted(true), []);

  const wire = story.wire;

  useEffect(() => {
    if (!mounted || !wire) return;
    const frame = frameRef.current;
    if (!frame) return;

    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let raf = 0;
    let start = 0;
    let ended = false;

    const chart = (reveal: number, flash: number) => {
      const c = canvasRef.current;
      if (!c) return;
      drawStoryChart(c, {
        bars: story.ohlc,
        eventIdx: story.event_idx,
        prevClose: story.prev_close,
        eventOpen: story.event_open,
        reveal,
        flash,
      });
    };

    const render = (t: number) => {
      // Scene opacities, cross-faded at each boundary.
      const bounds = [
        [0, S1],
        [S1, S2],
        [S2, S3],
        [S3, S4],
      ];
      bounds.forEach(([a, b], i) => {
        const el = sceneRefs[i].current;
        if (!el) return;
        const fadeIn = i === 0 ? 1 : seg(t, a - FADE / 2, a + FADE / 2);
        // The last scene never fades out — the player rests on it.
        const fadeOut = i === bounds.length - 1 ? 1 : 1 - seg(t, b - FADE / 2, b + FADE / 2);
        el.style.opacity = Math.min(fadeIn, fadeOut).toFixed(3);
      });

      // 1 — wire
      const p1 = seg(t, 0, S1);
      if (trackRef.current) {
        trackRef.current.style.transform = `translateY(${-(p1 * 46).toFixed(2)}%)`;
      }
      if (countRef.current) {
        countRef.current.textContent = String(
          Math.round(easeOut(clamp01(p1 / 0.82)) * wire.total),
        );
      }
      if (clockRef.current) {
        clockRef.current.textContent = `07:00:0${Math.min(Math.floor(p1 * 4), 3)}`;
      }

      // 2 — funnel, one number at a time
      const p2 = seg(t, S1, S2);
      [
        [0.02, 0.18],
        [0.3, 0.46],
        [0.58, 0.76],
      ].forEach(([a, b], i) => {
        const el = funnelRefs[i].current;
        if (el) el.style.opacity = seg(p2, a, b).toFixed(2);
      });

      // 4 — chart draws, then the counters roll
      const p4 = seg(t, S3, S4);
      chart(clamp01(p4 / 0.42), seg(p4, 0.42, 0.6));
      const k = easeOut(seg(p4, 0.44, 0.78));
      if (toRef.current) {
        toRef.current.textContent = fmtPence(
          story.prev_close + (story.event_open - story.prev_close) * k,
        );
      }
      if (pctRef.current) pctRef.current.textContent = fmtGap(story.gap_pct * k);
    };

    // Jump straight to the resting frame — used by reduced-motion and by a tab
    // going into the background.
    const finish = () => {
      if (ended) return;
      ended = true;
      if (raf) cancelAnimationFrame(raf);
      raf = 0;
      render(S4);
    };

    const tick = (now: number) => {
      if (!start) start = now;
      const t = now - start;
      render(t);
      if (t >= S4) {
        ended = true;
        raf = 0;
        return;
      }
      raf = requestAnimationFrame(tick);
    };

    if (reduce) {
      finish();
      return;
    }

    let io: IntersectionObserver | null = null;
    const begin = () => {
      if (ended || raf) return;
      start = 0;
      raf = requestAnimationFrame(tick);
    };
    if ("IntersectionObserver" in window) {
      io = new IntersectionObserver(
        (entries) => {
          for (const e of entries) {
            if (e.isIntersecting) {
              begin();
              io?.disconnect();
              io = null;
            }
          }
        },
        { threshold: 0.4 },
      );
      io.observe(frame);
    } else {
      begin();
    }

    // A backgrounded tab gets no frames, so the player would otherwise sit
    // frozen mid-scene when the visitor comes back to it.
    const onVisibility = () => {
      if (document.hidden) finish();
    };
    document.addEventListener("visibilitychange", onVisibility);

    // The canvas is resolution-dependent, so a resize needs a repaint.
    let resizeT: ReturnType<typeof setTimeout>;
    const onResize = () => {
      clearTimeout(resizeT);
      resizeT = setTimeout(() => {
        if (ended) render(S4);
      }, 180);
    };
    window.addEventListener("resize", onResize);

    return () => {
      if (raf) cancelAnimationFrame(raf);
      clearTimeout(resizeT);
      io?.disconnect();
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("resize", onResize);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mounted, story, wire]);

  if (!wire) return null;

  const ticker = story.symbol.replace(/\.L$/i, "");
  const negative = story.gap_pct < 0;
  const lines = [...wire.sample, ...wire.sample]; // doubled so the track can scroll

  return (
    <div className="am-phone" ref={frameRef} aria-hidden="true">
      <div className="am-phone-screen">
        {/* Scene 1 — the 07:00 wire */}
        <div className="am-ph-scene" ref={sceneRefs[0]} style={{ opacity: mounted ? 0 : 1 }}>
          <div className="am-ph-clock" ref={clockRef}>
            07:00:00
          </div>
          <div className="am-ph-feed">
            <div className="am-ph-track" ref={trackRef}>
              {lines.map((l, i) => (
                <div className="am-ph-line" key={i}>
                  {l[0]} <span className="am-ph-tic">{l[1]}</span> {l[2]}
                </div>
              ))}
            </div>
          </div>
          <div className="am-ph-plate">
            <div className="am-ph-count" ref={countRef}>
              {wire.total}
            </div>
            <div className="am-ph-label">announcements</div>
          </div>
          <div className="am-ph-sub">
            {wire.total} announcements landed before the open.
            <br />
            The market opens in an hour.
          </div>
        </div>

        {/* Scene 2 — the funnel */}
        <div className="am-ph-scene am-ph-funnel" ref={sceneRefs[1]}>
          <div className="am-ph-row am-ph-dim" ref={funnelRefs[0]}>
            <span className="am-ph-n">{wire.total}</span>
            <span className="am-ph-t">
              hit the wire
              <br />
              before 08:00
            </span>
          </div>
          <div className="am-ph-rule" />
          <div className="am-ph-row am-ph-live" ref={funnelRefs[1]}>
            <span className="am-ph-n">{wire.survived}</span>
            <span className="am-ph-t">
              survived
              <br />
              the filter
            </span>
          </div>
          <div className="am-ph-rule" />
          <div className="am-ph-row am-ph-key" ref={funnelRefs[2]}>
            <span className="am-ph-n">{wire.top}</span>
            <span className="am-ph-t">
              scored
              <br />
              80 or above
            </span>
          </div>
          <div className="am-ph-sub">
            {wire.top === 1 ? "One of them mattered." : `${wire.top} of them mattered.`}
            <br />
            Here&apos;s how you&apos;d know before the open.
          </div>
        </div>

        {/* Scene 3 — the score card */}
        <div className="am-ph-scene am-ph-card-scene" ref={sceneRefs[2]}>
          <div className="am-ph-stamp">Top score · 07:00</div>
          <div className="am-ph-card">
            <div className="am-ph-card-top">
              <div className="am-ph-co">
                <div className="am-ph-co-tic">{ticker}</div>
                <div className="am-ph-co-name">
                  {story.company_name}
                  {story.ftse_index ? ` · ${story.ftse_index}` : ""}
                </div>
              </div>
              <div className={`am-ph-badge ${negative ? "am-ph-neg" : "am-ph-pos"}`}>
                <div className="am-ph-badge-n">{story.llm_score}</div>
                <div className="am-ph-badge-l">{negative ? "Neg" : "Pos"}</div>
              </div>
            </div>
            <div className="am-ph-headline">RNS 07:00 — “{story.headline}”</div>
            <div className="am-ph-thesis">{story.thesis}</div>
          </div>
          <div className="am-ph-sub">
            {negative
              ? "The highest score of the morning was a negative one."
              : "The highest score of the morning."}
          </div>
        </div>

        {/* Scene 4 — the result */}
        <div className="am-ph-scene am-ph-result" ref={sceneRefs[3]}>
          <div className="am-ph-stamp">{ticker} · at the 08:00 open</div>
          <div className="am-ph-chart">
            <canvas ref={canvasRef} />
          </div>
          <div className="am-ph-move">
            <span className="am-ph-from">{fmtPence(story.prev_close)}</span>
            <span className="am-ph-arrow">→</span>
            <span className={`am-ph-to ${negative ? "am-ph-c-neg" : "am-ph-c-pos"}`} ref={toRef}>
              {fmtPence(story.event_open)}
            </span>
          </div>
          <div className={`am-ph-pct ${negative ? "am-ph-c-neg" : "am-ph-c-pos"}`} ref={pctRef}>
            {fmtGap(story.gap_pct)}
          </div>
          <div className="am-ph-cap">
            Gap from the previous close. Flagged an hour earlier.
          </div>
        </div>
      </div>
    </div>
  );
}
