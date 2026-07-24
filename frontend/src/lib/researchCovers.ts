// Cover art for research posts.
//
// Posts don't carry a designed cover image (the `image` field is the social/OG
// picture, often a chart), so the blog would otherwise be a wall of text cards.
// These bundled abstract renders (in /public/research/covers) give every post
// an atmospheric cover. Covers are assigned by the post's position in the list
// (round-robin), so the first COVERS.length posts are all different and every
// render gets used before any repeats — far more variety than a slug hash,
// which collided badly with only a handful of posts. `header` (index hero) and
// `ember` (screener CTA) are fixed page furniture, outside the rotation.

export interface Cover {
  src: string;
  /** background-position for the crop, e.g. "50% 42%". */
  position: string;
}

const COVERS: Cover[] = [
  { src: "/research/covers/smoke.webp", position: "50% 42%" },
  { src: "/research/covers/glitter.webp", position: "50% 50%" },
  { src: "/research/covers/swirl.webp", position: "45% 55%" },
  { src: "/research/covers/burst.webp", position: "42% 38%" },
  { src: "/research/covers/mesh.webp", position: "55% 60%" },
  { src: "/research/covers/splash.webp", position: "28% 30%" },
  { src: "/research/covers/nebula.webp", position: "50% 62%" },
];

// The index header banner — the soft indigo wave, its dark upper area keeping
// the overlaid title legible.
export const HERO_COVER: Cover = { src: "/research/covers/header.webp", position: "45% 52%" };
export const CTA_COVER: Cover = { src: "/research/covers/ember.webp", position: "58% 50%" };

// Small deterministic string hash (djb2-ish). Only used as a fallback when a
// post's list position isn't known (e.g. an isolated article render).
function hashSlug(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (Math.imul(h, 31) + s.charCodeAt(i)) | 0;
  return Math.abs(h);
}

// Cover for a post. Pass its position in the (published-desc) list to get the
// round-robin assignment; omit it (or pass a negative index, meaning "not in
// the list") to fall back to a stable slug hash.
export function coverFor(post: { slug: string }, index?: number): Cover {
  const i =
    index != null && index >= 0
      ? index % COVERS.length
      : hashSlug(post.slug) % COVERS.length;
  return COVERS[i];
}
