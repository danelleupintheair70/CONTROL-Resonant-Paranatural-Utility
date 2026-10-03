import { useState } from 'react';

// A poster, or the title on a plain card when there is none or it fails to load.
export function Poster({ item }) {
  const [broken, setBroken] = useState(false);
  if (!item.poster || broken) return <div className="poster-fallback">{item.title}</div>;
  return <img className="poster-img" loading="lazy" src={item.poster} alt="" onError={() => setBroken(true)} />;
}
