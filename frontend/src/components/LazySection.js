"use client";
import { useEffect, useRef, useState } from "react";

// Defers mounting `children` (and whatever client bundle / fetches they pull
// in) until the section is close to entering the viewport. Reserves
// `minHeight` up front so nothing shifts when the real content swaps in —
// used to keep heavy below-the-fold chart tabs (recharts + their own API
// calls) out of the initial /markets page load.
export default function LazySection({ children, minHeight = 400, rootMargin = "400px" }) {
  const ref = useRef(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (visible || !ref.current) return;
    const el = ref.current;
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setVisible(true);
          io.disconnect();
        }
      },
      { rootMargin },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [visible, rootMargin]);

  return <div ref={ref} style={visible ? undefined : { minHeight }}>{visible ? children : null}</div>;
}
