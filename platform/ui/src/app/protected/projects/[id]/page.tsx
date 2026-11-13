"use client";

import { use, useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { IconArrowBackUp, IconPlus, IconRefresh, IconRocket, IconTrash, IconX } from "@tabler/icons-react";

import { useAuth } from "@/api/OgnaContext";
import { PageShell } from "@/components/page-shell";
import { StatusBadge } from "@/components/status-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  IN_TRANSITION,
  PlatformApiError,
  type Deployment,
  type DesiredState,
  type PlatformEvent,
  type ProjectView,
  formatDate,
  platformApi,
} from "@/lib/platform";

const POLL_MS = 5000;

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[8rem_1fr] gap-2 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className="min-w-0 break-all">{children ?? "—"}</span>
    </div>
  );
}

function DeleteProject({ view, onDeleted }: { view: ProjectView; onDeleted: () => void }) {
  const client = useAuth();
  const api = useMemo(() => platformApi(client), [client]);
  const [open, setOpen] = useState(false);
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const slug = view.project.slug;

  const remove = async () => {
    setBusy(true);
    try {
      await api.deleteProject(view.project.id);
      toast.success("Deleting the server…");
      setOpen(false);
      onDeleted();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not delete the project");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Popover open={open} onOpenChange={(o) => { setOpen(o); setConfirm(""); }}>
      <PopoverTrigger asChild>
        <Button size="sm" variant="outline" disabled={view.project.status === "deleting"}>
          <IconTrash /> Delete
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-80" align="end">
        <div className="grid gap-3">
          <div className="space-y-1">
            <h4 className="font-medium">Delete this project?</h4>
            <p className="text-sm text-muted-foreground">
              The server and everything on it are destroyed. This can&apos;t be undone.
            </p>
          </div>
          <Label htmlFor="confirm-slug" className="text-sm font-normal">
            Type <code className="font-mono">{slug}</code> to confirm
          </Label>
          <Input id="confirm-slug" value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="off" />
          <Button variant="destructive" disabled={confirm !== slug || busy} onClick={remove}>
            {busy ? "Deleting…" : "Delete project"}
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  );
}

type ConfigRow = { key: string; value: string };

function DeployForm({ view, onDeployed }: { view: ProjectView; onDeployed: () => void }) {
  const client = useAuth();
  const api = useMemo(() => platformApi(client), [client]);
  const current = view.current_deployment;
  const [image, setImage] = useState(current?.backend_image ?? "");
  const [stack, setStack] = useState(current?.stack_version ?? "");
  const [rows, setRows] = useState<ConfigRow[]>(
    Object.entries(current?.config ?? {}).map(([key, value]) => ({ key, value }))
  );
  const [busy, setBusy] = useState(false);

  const setRow = (i: number, patch: Partial<ConfigRow>) =>
    setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)));

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const config: Record<string, string> = {};
    for (const r of rows) {
      if (!r.key.trim()) continue;
      config[r.key.trim()] = r.value;
    }
    setBusy(true);
    try {
      const d = await api.deploy(view.project.id, {
        backend_image: image.trim(),
        ...(stack.trim() ? { stack_version: stack.trim() } : {}),
        config,
      });
      toast.success(`Deployed v${d.version}`);
      onDeployed();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Deploy failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="grid max-w-2xl gap-6">
      <div className="grid gap-2">
        <Label htmlFor="image">Backend image</Label>
        <Input
          id="image"
          required
          value={image}
          onChange={(e) => setImage(e.target.value)}
          placeholder="ghcr.io/you/api@sha256:… or ghcr.io/you/api:1.0.0"
          className="font-mono"
        />
        <p className="text-xs text-muted-foreground">
          Prefer a <code>@sha256:</code> digest: a tag can point to different code later.
        </p>
      </div>
      <div className="grid gap-2">
        <Label htmlFor="stack">OGNA stack version</Label>
        <Input id="stack" value={stack} onChange={(e) => setStack(e.target.value)} placeholder="main (default) or 1.4.2" />
      </div>
      <div className="grid gap-2">
        <Label>Configuration</Label>
        <p className="text-xs text-muted-foreground">
          Non-secret settings passed to your API, e.g. <code>LOG_LEVEL</code>. Keys are UPPER_SNAKE_CASE.
        </p>
        {rows.map((r, i) => (
          <div key={i} className="flex gap-2">
            <Input
              aria-label="Key"
              value={r.key}
              onChange={(e) => setRow(i, { key: e.target.value.toUpperCase() })}
              placeholder="KEY"
              className="font-mono"
            />
            <Input aria-label="Value" value={r.value} onChange={(e) => setRow(i, { value: e.target.value })} placeholder="value" />
            <Button type="button" variant="ghost" size="icon" aria-label="Remove" onClick={() => setRows((rs) => rs.filter((_, j) => j !== i))}>
              <IconX />
            </Button>
          </div>
        ))}
        <div>
          <Button type="button" variant="outline" size="sm" onClick={() => setRows((rs) => [...rs, { key: "", value: "" }])}>
            <IconPlus /> Add setting
          </Button>
        </div>
      </div>
      <div>
        <Button type="submit" disabled={busy || !image.trim()}>
          <IconRocket /> {busy ? "Deploying…" : current ? `Deploy v${view.project.current_version + 1}` : "Deploy v1"}
        </Button>
      </div>
    </form>
  );
}

function Deployments({
  view,
  deployments,
  onChanged,
}: {
  view: ProjectView;
  deployments: Deployment[];
  onChanged: () => void;
}) {
  const client = useAuth();
  const api = useMemo(() => platformApi(client), [client]);
  const [busyVersion, setBusyVersion] = useState<number | null>(null);

  const rollback = async (version: number) => {
    setBusyVersion(version);
    try {
      const d = await api.rollback(view.project.id, version);
      toast.success(`v${d.version} rolls back to v${version}`);
      onChanged();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Rollback failed");
    } finally {
      setBusyVersion(null);
    }
  };

  if (deployments.length === 0) {
    return <p className="text-sm text-muted-foreground">No deployments yet. Use the Deploy tab to ship your API.</p>;
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Version</TableHead>
          <TableHead>Image</TableHead>
          <TableHead>Stack</TableHead>
          <TableHead>When</TableHead>
          <TableHead />
        </TableRow>
      </TableHeader>
      <TableBody>
        {deployments.map((d) => {
          const isCurrent = d.version === view.project.current_version;
          return (
            <TableRow key={d.version}>
              <TableCell className="whitespace-nowrap">
                v{d.version}{" "}
                {isCurrent && <Badge variant="outline">current</Badge>}
                {d.reason === "rollback" && (
                  <span className="text-xs text-muted-foreground"> ↩ v{d.rolled_back_from}</span>
                )}
              </TableCell>
              <TableCell className="max-w-[24rem] truncate font-mono text-xs" title={d.backend_image}>
                {d.backend_image}
              </TableCell>
              <TableCell>{d.stack_version}</TableCell>
              <TableCell className="whitespace-nowrap text-sm text-muted-foreground">{formatDate(d.created_at)}</TableCell>
              <TableCell className="text-right">
                {!isCurrent && (
                  <Button size="sm" variant="ghost" disabled={busyVersion !== null} onClick={() => rollback(d.version)}>
                    <IconArrowBackUp /> {busyVersion === d.version ? "Rolling back…" : "Roll back"}
                  </Button>
                )}
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}

export default function ProjectPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const client = useAuth();
  const router = useRouter();
  const api = useMemo(() => platformApi(client), [client]);
  const [view, setView] = useState<ProjectView | null>(null);
  const [deployments, setDeployments] = useState<Deployment[]>([]);
  const [events, setEvents] = useState<PlatformEvent[]>([]);
  const [desired, setDesired] = useState<DesiredState | null>(null);
  const [syncing, setSyncing] = useState(false);

  const load = useCallback(async () => {
    try {
      const [v, d, e, s] = await Promise.all([
        api.project(id),
        api.deployments(id),
        api.events(id),
        api.desiredState(id),
      ]);
      setView(v);
      setDeployments(d);
      setEvents(e);
      setDesired(s);
    } catch (err) {
      if (err instanceof PlatformApiError && err.status === 404) {
        toast.message("Project not found (it may have been deleted)");
        router.replace("/protected/projects");
        return;
      }
      toast.error(err instanceof Error ? err.message : "Could not load the project");
    }
  }, [api, id, router]);

  useEffect(() => {
    load();
  }, [load]);

  const inTransition = view ? IN_TRANSITION.includes(view.project.status) : false;
  useEffect(() => {
    if (!inTransition) return;
    const t = setInterval(load, POLL_MS);
    return () => clearInterval(t);
  }, [inTransition, load]);

  const sync = async () => {
    setSyncing(true);
    try {
      setView(await api.syncProject(id));
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Sync failed");
    } finally {
      setSyncing(false);
    }
  };

  if (!view) {
    return (
      <PageShell title="Project">
        <Skeleton className="h-40" />
        <Skeleton className="h-64" />
      </PageShell>
    );
  }

  const { project, server } = view;
  const canDeploy = project.status !== "deleting";

  return (
    <PageShell
      title={project.name}
      actions={
        <>
          <Button size="sm" variant="ghost" onClick={sync} disabled={syncing}>
            <IconRefresh className={syncing ? "animate-spin" : undefined} /> Refresh
          </Button>
          <DeleteProject view={view} onDeleted={load} />
        </>
      }
    >
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between gap-2">
              <CardTitle>Overview</CardTitle>
              <StatusBadge status={project.status} />
            </div>
            {project.status_detail && <CardDescription>{project.status_detail}</CardDescription>}
          </CardHeader>
          <CardContent className="grid gap-2">
            <Field label="URL">{view.url}</Field>
            <Field label="Slug">{project.slug}</Field>
            <Field label="Plan">{project.plan_id}</Field>
            <Field label="Deployed">
              {view.current_deployment ? `v${project.current_version}: ${view.current_deployment.backend_image}` : "Nothing yet"}
            </Field>
            <Field label="Created">{formatDate(project.created_at)}</Field>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Server</CardTitle>
            <CardDescription>
              {server ? `${server.provider} · ${server.server_type} · ${server.location}` : "Not created yet"}
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-2">
            <Field label="Name">{server?.name}</Field>
            <Field label="Status">{server?.status}</Field>
            <Field label="IPv4">{server?.ipv4}</Field>
            <Field label="IPv6">{server?.ipv6}</Field>
            <Field label="Provider id">{server?.provider_server_id}</Field>
          </CardContent>
        </Card>
      </div>

      <Tabs defaultValue="deployments">
        <TabsList>
          <TabsTrigger value="deployments">Deployments</TabsTrigger>
          <TabsTrigger value="deploy" disabled={!canDeploy}>Deploy</TabsTrigger>
          <TabsTrigger value="events">Events</TabsTrigger>
          <TabsTrigger value="desired">Desired state</TabsTrigger>
        </TabsList>
        <TabsContent value="deployments" className="pt-4">
          <Deployments view={view} deployments={deployments} onChanged={load} />
        </TabsContent>
        <TabsContent value="deploy" className="pt-4">
          {canDeploy && <DeployForm key={project.current_version} view={view} onDeployed={load} />}
        </TabsContent>
        <TabsContent value="events" className="pt-4">
          {events.length === 0 ? (
            <p className="text-sm text-muted-foreground">No events yet.</p>
          ) : (
            <ol className="grid gap-3">
              {events.map((e, i) => (
                <li key={e.id ?? i} className="grid grid-cols-[10rem_1fr] gap-3 text-sm">
                  <span className="text-muted-foreground">{formatDate(e.created_at)}</span>
                  <span>
                    <Badge variant="outline" className="mr-2">{e.kind}</Badge>
                    {e.message}
                  </span>
                </li>
              ))}
            </ol>
          )}
        </TabsContent>
        <TabsContent value="desired" className="pt-4">
          <p className="mb-2 text-sm text-muted-foreground">
            What this server should be running. The OGNA agent on the server will apply it.
          </p>
          <pre className="overflow-x-auto rounded-md border bg-muted/40 p-4 text-xs">
            {JSON.stringify(desired, null, 2)}
          </pre>
        </TabsContent>
      </Tabs>
    </PageShell>
  );
}
