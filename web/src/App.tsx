// App shell: TanStack Query provider + React Router 8 routes
// (D-04, D-12, UI-SPEC §5).
//
// `createBrowserRouter` is imported from "react-router" (NOT
// "react-router-dom") per RESEARCH Pitfall 6 — react-router 8 merges the
// old react-router-dom entry so the legacy package must NOT be installed.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createBrowserRouter, RouterProvider } from "react-router"

import HistoryPage from "./pages/HistoryPage"
import DetailPage from "./pages/DetailPage"

const queryClient = new QueryClient()

const router = createBrowserRouter([
  { path: "/", element: <HistoryPage /> },
  { path: "/jobs/:id", element: <DetailPage /> },
])

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  )
}