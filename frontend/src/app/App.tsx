import { RouterProvider } from "react-router-dom";
import { router } from "./router";

/**
 * App shell: delegates routing to the react-router data router defined in
 * ./router.tsx. The router's root layout route mounts the persistent NavBar
 * around every page (<Outlet/>), so navigation stays visible across the SPA.
 */
export default function App() {
  return <RouterProvider router={router} />;
}
