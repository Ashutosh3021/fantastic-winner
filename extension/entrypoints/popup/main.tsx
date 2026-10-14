import { createRoot } from "react-dom/client";

import "../../src/ui/styles.css";
import { injectDocumentFonts } from "../../src/ui/fonts";
import { Popup } from "./Popup";

const container = document.getElementById("root");
if (!container) throw new Error("Popup root missing.");

injectDocumentFonts();

createRoot(container).render(
  <div className="min-h-0">
    <Popup />
  </div>,
);