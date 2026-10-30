// Every screen holds patient data: nothing is served without a signed-in team member, except the sign-in itself.
export { default } from "next-auth/middleware";

export const config = {
  matcher: ["/((?!api/auth|login|_next/static|_next/image|favicon.ico).*)"],
};
