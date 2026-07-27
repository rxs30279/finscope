import type { StoryBar } from "./landingStory";

/**
 * Candle painter for the story-of-the-week block, ported from the 34-second
 * Shorts storyboard. Shared by the phone player (which animates it) and the
 * static card below it (which draws the finished frame once).
 *
 * Two conventions here are load-bearing and must not be "fixed":
 *
 *   1. Candles are coloured close-vs-PREVIOUS-close, not close-vs-open. Henry
 *      Boot opened 140p and closed 154p on 22 Jul — a green candle by the open,
 *      but the session is 12p below the prior close, and that drop is the whole
 *      point of the scene.
 *   2. The shaded band spans previous close -> announcement-day open. That gap
 *      IS the story: the reaction the score called before anyone could trade it.
 */

export const STORY_UP = "#42e58a"; // --green in landing.css
export const STORY_DOWN = "#e5524b"; // --red
const MUTED = "rgba(154, 166, 181, 0.5)"; // context bars
const BASELINE = "rgba(154, 166, 181, 0.34)";
const LABEL = "rgba(154, 166, 181, 0.55)";
const LABEL_EVENT = "rgba(232, 237, 242, 0.85)";

export interface DrawOpts {
  bars: StoryBar[];
  eventIdx: number;
  prevClose: number;
  eventOpen: number;
  /** 0-1: how much of the series has been drawn in. */
  reveal: number;
  /** 0-1: how strongly the event bar and its gap band are lit. */
  flash: number;
}

export function drawStoryChart(canvas: HTMLCanvasElement, o: DrawOpts): void {
  const rect = canvas.getBoundingClientRect();
  if (!rect.width || !rect.height) return;
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = Math.round(rect.width * dpr);
  canvas.height = Math.round(rect.height * dpr);
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

  const W = rect.width;
  const H = rect.height;
  ctx.clearRect(0, 0, W, H);

  const padT = H * 0.08;
  const padB = H * 0.14;
  const padX = W * 0.04;

  // Include prevClose in the range: the gap band is drawn to it, and on a big
  // gap it can sit outside every wick.
  let lo = Math.min(o.prevClose, ...o.bars.map((b) => b[3]));
  let hi = Math.max(o.prevClose, ...o.bars.map((b) => b[2]));
  let span = hi - lo || 1;
  lo -= span * 0.08;
  hi += span * 0.08;
  span = hi - lo;
  const y = (v: number) => padT + ((hi - v) / span) * (H - padT - padB);

  const n = o.bars.length;
  const slot = (W - padX * 2) / n;
  const bw = Math.min(slot * 0.52, W * 0.075);

  // Dashed baseline at the close the market last saw before the news.
  ctx.strokeStyle = BASELINE;
  ctx.lineWidth = 1;
  ctx.setLineDash([3, 4]);
  ctx.beginPath();
  ctx.moveTo(padX, y(o.prevClose));
  ctx.lineTo(W - padX, y(o.prevClose));
  ctx.stroke();
  ctx.setLineDash([]);

  const shown = Math.min(n, Math.floor(o.reveal * n + 0.0001));

  // The gap band — previous close to the announcement-day open.
  if (shown > o.eventIdx) {
    const gx = padX + slot * o.eventIdx;
    ctx.globalAlpha = 0.13 + 0.12 * o.flash;
    ctx.fillStyle = o.eventOpen < o.prevClose ? STORY_DOWN : STORY_UP;
    ctx.fillRect(
      gx - slot * 0.15,
      Math.min(y(o.prevClose), y(o.eventOpen)),
      slot * 1.3,
      Math.abs(y(o.eventOpen) - y(o.prevClose)),
    );
    ctx.globalAlpha = 1;
  }

  ctx.font = `${Math.max(9, H * 0.062)}px ui-monospace, Consolas, monospace`;
  ctx.textAlign = "center";

  for (let i = 0; i < shown; i++) {
    const b = o.bars[i];
    const open = b[1];
    const close = b[4];
    // Defensive against bad ticks: some price_history rows have low > close.
    const high = Math.max(b[2], open, close);
    const low = Math.min(b[3], open, close);
    const cx = padX + slot * i + slot / 2;
    const isEvent = i === o.eventIdx;
    const prev = i > 0 ? o.bars[i - 1][4] : o.prevClose;
    const col = isEvent ? (close >= prev ? STORY_UP : STORY_DOWN) : MUTED;

    ctx.globalAlpha = isEvent ? 0.35 + 0.65 * o.flash : 1;
    ctx.strokeStyle = col;
    ctx.fillStyle = col;
    ctx.lineWidth = Math.max(1, bw * 0.14);
    ctx.beginPath();
    ctx.moveTo(cx, y(high));
    ctx.lineTo(cx, y(low));
    ctx.stroke();
    ctx.fillRect(
      cx - bw / 2,
      Math.min(y(open), y(close)),
      bw,
      Math.max(Math.abs(y(close) - y(open)), 1.5),
    );
    ctx.globalAlpha = 1;

    ctx.fillStyle = isEvent ? LABEL_EVENT : LABEL;
    ctx.fillText(b[0], cx, H - padB * 0.28);
  }
}
