import { useEffect, useRef } from 'react';

const POLL_INTERVAL = 3000;

export default function usePolling(callback, enabled = true) {
  const savedCallback = useRef(callback);

  useEffect(() => {
    savedCallback.current = callback;
  }, [callback]);

  useEffect(() => {
    if (!enabled) return;
    const id = setInterval(() => savedCallback.current(), POLL_INTERVAL);
    return () => clearInterval(id);
  }, [enabled]);
}
