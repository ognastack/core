"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { IconPlus, IconServer2, IconWorld } from "@tabler/icons-react";

import { useAuth } from "@/api/OgnaContext";
import { PageShell } from "@/components/page-shell";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import {
  IN_TRANSITION,
  type Account,
  type ProjectView,
  type Region,
  platformApi,
} from "@/lib/platform";

const POLL_MS = 5000;

function CreateProjectSheet({
  open,
  onOpenChange,
  regions,
  account,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  regions: Region[];
  account: Account | null;
  onCreated: (view: ProjectView) => void;
}) {
  const client = useAuth();
  const api = useMemo(() => platformApi(client), [client]);
  const [name, setName] = useState("");
  const [region, setRegion] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (open) {
      setName("");
      setRegion(regions.find((r) => r.is_default)?.id ?? regions[0]?.id ?? "");
    }
  }, [open, regions]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) {
      toast.error("Give your project a name");
      return;
    }
    setBusy(true);
    try {
      const view = await api.createProject(name.trim(), region || undefined);
      toast.success(`Creating ${view.project.name}…`);
      onOpenChange(false);
      onCreated(view);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not create the project");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent>
        <form onSubmit={submit} className="flex h-full flex-col">
          <SheetHeader>
            <SheetTitle>New project</SheetTitle>
            <SheetDescription>
              A dedicated server with its own OGNA stack
              {account ? ` (${account.plan.name} plan: ${account.plan.server_type})` : ""}.
            </SheetDescription>
          </SheetHeader>
          <div className="grid gap-6 px-4">
            <div className="grid gap-2">
              <Label htmlFor="project-name">Name</Label>
              <Input
                id="project-name"
                value={name}
                maxLength={63}
                autoFocus
                placeholder="My shop"
                onChange={(e) => setName(e.target.value)}
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="project-region">Region</Label>
              <Select value={region} onValueChange={setRegion}>
                <SelectTrigger id="project-region" className="w-full">
                  <SelectValue placeholder="Choose a region" />
                </SelectTrigger>
                <SelectContent>
                  {regions.map((r) => (
                    <SelectItem key={r.id} value={r.id}>
                      {r.name} ({r.id})
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <SheetFooter>
            <Button type="submit" disabled={busy}>
              {busy ? "Creating…" : "Create project"}
            </Button>
          </SheetFooter>
        </form>
      </SheetContent>
    </Sheet>
  );
}

function ProjectCard({ view }: { view: ProjectView }) {
  const { project, server } = view;
  return (
    <Link href={`/protected/projects/${project.id}`} className="block">
      <Card className="h-full transition-colors hover:bg-muted/40">
        <CardHeader>
          <div className="flex items-start justify-between gap-2">
            <CardTitle className="truncate">{project.name}</CardTitle>
            <StatusBadge status={project.status} />
          </div>
          <CardDescription className="truncate">{project.slug}</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-1 text-sm text-muted-foreground">
          <div className="flex items-center gap-2">
            <IconServer2 className="size-4" />
            {project.server_type} · {project.region}
            {server?.ipv4 ? ` · ${server.ipv4}` : ""}
          </div>
          <div className="flex items-center gap-2 truncate">
            <IconWorld className="size-4 shrink-0" />
            <span className="truncate">{view.url}</span>
          </div>
          <div>{project.current_version ? `Deployed v${project.current_version}` : "Nothing deployed yet"}</div>
          {project.status_detail && <div className="text-xs">{project.status_detail}</div>}
        </CardContent>
      </Card>
    </Link>
  );
}

export default function ProjectsPage() {
  const client = useAuth();
  const router = useRouter();
  const api = useMemo(() => platformApi(client), [client]);
  const [projects, setProjects] = useState<ProjectView[] | null>(null);
  const [account, setAccount] = useState<Account | null>(null);
  const [regions, setRegions] = useState<Region[]>([]);
  const [sheetOpen, setSheetOpen] = useState(false);

  const load = useCallback(async () => {
    try {
      const [p, a] = await Promise.all([api.projects(), api.account()]);
      setProjects(p);
      setAccount(a);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not load projects");
      setProjects((prev) => prev ?? []);
    }
  }, [api]);

  useEffect(() => {
    load();
    api.regions().then(setRegions).catch(() => setRegions([]));
  }, [api, load]);

  // Keep polling while anything is being created or deleted
  const busy = projects?.some((v) => IN_TRANSITION.includes(v.project.status)) ?? false;
  useEffect(() => {
    if (!busy) return;
    const t = setInterval(load, POLL_MS);
    return () => clearInterval(t);
  }, [busy, load]);

  const atLimit = account ? account.projects_used >= account.projects_allowed : false;

  return (
    <PageShell
      title="Projects"
      actions={
        <Button size="sm" onClick={() => setSheetOpen(true)} disabled={atLimit} title={atLimit ? "Plan limit reached" : undefined}>
          <IconPlus /> New project
        </Button>
      }
    >
      {account && (
        <p className="text-sm text-muted-foreground">
          {account.projects_used} of {account.projects_allowed} project
          {account.projects_allowed === 1 ? "" : "s"} used on the <strong>{account.plan.name}</strong> plan.
          {atLimit && (
            <>
              {" "}
              <Link href="/protected/account" className="underline underline-offset-4">
                See plans
              </Link>
            </>
          )}
        </p>
      )}

      {projects === null ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-40" />
          ))}
        </div>
      ) : projects.length === 0 ? (
        <Card>
          <CardHeader>
            <CardTitle>No projects yet</CardTitle>
            <CardDescription>
              Each project is a server running its own OGNA stack: database, auth, storage, GraphQL and your API.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button onClick={() => setSheetOpen(true)} disabled={atLimit}>
              <IconPlus /> Create your first project
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {projects.map((v) => (
            <ProjectCard key={v.project.id} view={v} />
          ))}
        </div>
      )}

      <CreateProjectSheet
        open={sheetOpen}
        onOpenChange={setSheetOpen}
        regions={regions}
        account={account}
        onCreated={(view) => router.push(`/protected/projects/${view.project.id}`)}
      />
    </PageShell>
  );
}
