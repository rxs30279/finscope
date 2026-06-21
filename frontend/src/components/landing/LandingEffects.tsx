"use client";

import { useEffect } from "react";

/**
 * Client-only behaviour for the marketing landing:
 *   1. the animated candlestick background painted into #am-chart, and
 *   2. the scroll-reveal that fades `.am-reveal` elements in as they enter view.
 *
 * The markup (canvas element, reveal classes) is server-rendered in page.tsx so
 * the copy is in the initial HTML for crawlers; this component only drives motion.
 */
export default function LandingEffects() {
  useEffect(() => {
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    // ---- Candlestick background ----
    const cv = document.getElementById("am-chart") as HTMLCanvasElement | null;
    let raf = 0;
    let resizeT: ReturnType<typeof setTimeout>;
    const cleanups: Array<() => void> = [];

    if (cv) {
      const ctx = cv.getContext("2d");
      if (ctx) {
        const GREEN = "#42e58a";
        const RED = "#e5524b";
        let W = 0, H = 0, cw = 9, gap = 9, baseY = 0, scaleY = 4, price = 100, t = 0;
        type Candle = { o: number; c: number; h: number; l: number; up: boolean };
        let candles: Candle[] = [];

        const rand = (a: number, b: number) => a + Math.random() * (b - a);

        const reshape = (k: Candle) => {
          k.h = Math.max(k.o, k.c) + rand(0.4, 2.6);
          k.l = Math.min(k.o, k.c) - rand(0.4, 2.6);
          k.up = k.c >= k.o;
        };
        const makeCandle = (): Candle => {
          const o = price;
          const drift = rand(-3, 3) + (100 - o) * 0.04; // mean-revert toward 100
          const c = o + drift;
          price = c;
          const k: Candle = { o, c, h: 0, l: 0, up: c >= o };
          reshape(k);
          return k;
        };

        const build = () => {
          const dpr = Math.min(window.devicePixelRatio || 1, 2);
          W = window.innerWidth || document.documentElement.clientWidth || 360;
          H = window.innerHeight || document.documentElement.clientHeight || 640;
          cv.width = Math.round(W * dpr);
          cv.height = Math.round(H * dpr);
          cv.style.width = W + "px";
          cv.style.height = H + "px";
          ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

          cw = W < 560 ? 7 : 9;
          gap = Math.round(cw * 0.95);
          const count = Math.ceil(W / (cw + gap)) + 4;

          baseY = H * 0.5;
          scaleY = Math.max(3.5, H * 0.018);
          price = 100;
          candles = [];
          for (let i = 0; i < count; i++) candles.push(makeCandle());
          for (let i = 1; i < candles.length; i++) {
            candles[i].o = candles[i - 1].c;
            reshape(candles[i]);
          }
        };

        const draw = () => {
          ctx.clearRect(0, 0, W, H);
          const total = cw + gap;
          const off = reduce ? 0 : t % total;

          for (let i = 0; i < candles.length; i++) {
            const k = candles[i];
            const x = Math.round(i * total - off);
            const cx = x + cw / 2;
            const yO = baseY - (k.o - 100) * scaleY;
            const yC = baseY - (k.c - 100) * scaleY;
            const yH = baseY - (k.h - 100) * scaleY;
            const yL = baseY - (k.l - 100) * scaleY;
            const col = k.up ? GREEN : RED;

            ctx.strokeStyle = col;
            ctx.fillStyle = col;
            ctx.globalAlpha = 0.9;
            ctx.lineWidth = Math.max(1, cw * 0.12);
            ctx.beginPath();
            ctx.moveTo(cx, yH);
            ctx.lineTo(cx, yL);
            ctx.stroke();

            const top = Math.min(yO, yC);
            const h = Math.max(2, Math.abs(yC - yO));
            ctx.globalAlpha = k.up ? 0.95 : 0.9;
            ctx.fillRect(x, top, cw, h);
          }
          ctx.globalAlpha = 1;

          if (!reduce) {
            t += 0.45;
            if (t >= total) {
              t -= total;
              candles.shift();
              const last = candles[candles.length - 1];
              price = last.c;
              const nk = makeCandle();
              nk.o = last.c;
              reshape(nk);
              candles.push(nk);
            }
          }
          raf = requestAnimationFrame(draw);
        };

        const onResize = () => {
          clearTimeout(resizeT);
          resizeT = setTimeout(build, 180);
        };
        window.addEventListener("resize", onResize);
        window.addEventListener("orientationchange", onResize);
        cleanups.push(() => {
          window.removeEventListener("resize", onResize);
          window.removeEventListener("orientationchange", onResize);
        });

        // Stop painting while the tab is hidden, resume when it returns —
        // the background is fixed and always on-screen, so this otherwise runs
        // forever and burns CPU/battery on a backgrounded tab.
        const onVisibility = () => {
          cancelAnimationFrame(raf);
          if (!document.hidden) raf = requestAnimationFrame(draw);
        };
        document.addEventListener("visibilitychange", onVisibility);
        cleanups.push(() => document.removeEventListener("visibilitychange", onVisibility));

        build();
        raf = requestAnimationFrame(draw);
      }
    }

    // ---- Scroll reveal ----
    const els = Array.from(document.querySelectorAll<HTMLElement>(".am-reveal"));
    let io: IntersectionObserver | null = null;
    if ("IntersectionObserver" in window) {
      io = new IntersectionObserver(
        (entries) => {
          entries.forEach((e, i) => {
            if (e.isIntersecting) {
              setTimeout(() => e.target.classList.add("in"), i * 70);
              io?.unobserve(e.target);
            }
          });
        },
        { threshold: 0.15 },
      );
      els.forEach((el) => io?.observe(el));
    } else {
      els.forEach((el) => el.classList.add("in"));
    }

    return () => {
      cancelAnimationFrame(raf);
      clearTimeout(resizeT);
      cleanups.forEach((fn) => fn());
      io?.disconnect();
    };
  }, []);

  return null;
}
