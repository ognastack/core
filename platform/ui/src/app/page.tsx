import Link from "next/link";
import { IconInnerShadowTop } from "@tabler/icons-react";
import { Button } from "@/components/ui/button";

export default function Landing() {
  return (
    <main className="flex min-h-svh flex-col items-center justify-center gap-8 p-6 text-center">
      <div className="flex items-center gap-2 text-2xl font-semibold">
        <IconInnerShadowTop className="size-7" /> OGNA Platform
      </div>
      <p className="max-w-md text-muted-foreground">
        Your own backend stack on a dedicated server: Postgres, auth, storage, GraphQL and your API, deployed in minutes.
      </p>
      <div className="flex gap-3">
        <Button asChild>
          <Link href="/account/signup">Get started</Link>
        </Button>
        <Button asChild variant="outline">
          <Link href="/account/login">Log in</Link>
        </Button>
      </div>
    </main>
  );
}
