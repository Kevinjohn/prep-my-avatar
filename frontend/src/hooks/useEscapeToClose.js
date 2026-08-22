import { useEffect, useRef } from 'react';

/** Close the current surface when Escape is pressed and closing is enabled. */
export function useEscapeToClose(onClose, enabled = true) {
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  useEffect(() => {
    if (!enabled) return undefined;
    const closeOnEscape = (event) => {
      if (event.key === 'Escape') onCloseRef.current();
    };
    window.addEventListener('keydown', closeOnEscape);
    return () => window.removeEventListener('keydown', closeOnEscape);
  }, [enabled]);
}
