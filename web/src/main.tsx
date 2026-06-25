// Vite entry (D-12). Renders <App/> which wires the React Router 8
// `createBrowserRouter` routes (/ -> HistoryPage, /jobs/:id -> DetailPage)
// inside a TanStack Query provider (05-02a hooks need it).
import { StrictMode } from "react"
import { createRoot } from "react-dom/client"

import App from "./App.tsx"
import "./styles.css"

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)