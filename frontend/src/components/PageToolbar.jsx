import { useLayoutEffect, useState } from "react";
import { createPortal } from "react-dom";

export default function PageToolbar({ active = true, children }) {
  const [target, setTarget] = useState(null);

  useLayoutEffect(() => {
    setTarget(document.getElementById("page-toolbar-slot"));
  }, []);

  if (!active || !target) return null;
  return createPortal(<div className="page-toolbar-content">{children}</div>, target);
}
