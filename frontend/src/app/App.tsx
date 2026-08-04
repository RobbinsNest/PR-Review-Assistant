import { RouterProvider } from "react-router-dom";
import { router } from "./router";

/**
 * App shell: delegates routing to the react-router data router defined in
 * ./router.tsx. Pages are mounted per route (T15/T16 fill in the remaining
 * routes).
 */
export default function App() {
  return <RouterProvider router={router} />;
}
