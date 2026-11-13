"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { IconCheck } from "@tabler/icons-react";

import { useAuth } from "@/api/OgnaContext";
import { PageShell } from "@/components/page-shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { type Account, type Plan, formatPrice, platformApi } from "@/lib/platform";

function AdminSetPlan({ plans, onChanged }: { plans: Plan[]; onChanged: () => void }) {
  const client = useAuth();
  const api = useMemo(() => platformApi(client), [client]);
  const [userId, setUserId] = useState("");
  const [planId, setPlanId] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      const a = await api.setPlan(userId.trim(), planId);
      toast.success(`${a.user_id} is now on ${a.plan.name}`);
      onChanged();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not change the plan");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Change a user&apos;s plan</CardTitle>
        <CardDescription>Platform admins only. Downgrades below a user&apos;s current usage are refused.</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={submit} className="grid max-w-xl gap-4 sm:grid-cols-[1fr_12rem_auto] sm:items-end">
          <div className="grid gap-2">
            <Label htmlFor="admin-user">User id</Label>
            <Input id="admin-user" value={userId} onChange={(e) => setUserId(e.target.value)} placeholder="user id" />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="admin-plan">Plan</Label>
            <Select value={planId} onValueChange={setPlanId}>
              <SelectTrigger id="admin-plan" className="w-full">
                <SelectValue placeholder="Plan" />
              </SelectTrigger>
              <SelectContent>
                {plans.map((p) => (
                  <SelectItem key={p.id} value={p.id}>
                    {p.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <Button type="submit" disabled={busy || !userId.trim() || !planId}>
            {busy ? "Saving…" : "Set plan"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

export default function AccountPage() {
  const client = useAuth();
  const api = useMemo(() => platformApi(client), [client]);
  const [account, setAccount] = useState<Account | null>(null);
  const [plans, setPlans] = useState<Plan[]>([]);

  const load = useCallback(async () => {
    try {
      const [a, p] = await Promise.all([api.account(), api.plans()]);
      setAccount(a);
      setPlans(p);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not load your account");
    }
  }, [api]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <PageShell title="Plan & usage">
      {!account ? (
        <Skeleton className="h-32" />
      ) : (
        <Card>
          <CardHeader>
            <CardTitle>{account.plan.name} plan</CardTitle>
            <CardDescription>
              {account.projects_used} of {account.projects_allowed} project
              {account.projects_allowed === 1 ? "" : "s"} used · each server is a {account.plan.server_type}
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-2 text-sm">
            <div className="h-2 w-full max-w-md overflow-hidden rounded-full bg-muted">
              <div
                className="h-full bg-primary"
                style={{
                  width: `${account.projects_allowed ? Math.min(100, (100 * account.projects_used) / account.projects_allowed) : 100}%`,
                }}
              />
            </div>
            <p className="text-muted-foreground">
              Your user id: <code className="font-mono">{account.user_id}</code>
            </p>
          </CardContent>
        </Card>
      )}

      <div className="grid gap-4 md:grid-cols-3">
        {plans.map((p) => {
          const current = account?.plan.id === p.id;
          return (
            <Card key={p.id} className={current ? "border-primary" : undefined}>
              <CardHeader>
                <div className="flex items-center justify-between">
                  <CardTitle>{p.name}</CardTitle>
                  {current && (
                    <Badge>
                      <IconCheck /> Current
                    </Badge>
                  )}
                </div>
                <CardDescription className="text-lg font-medium text-foreground">
                  {formatPrice(p.monthly_price_cents)}
                </CardDescription>
              </CardHeader>
              <CardContent className="grid gap-1 text-sm text-muted-foreground">
                <span>
                  Up to {p.max_projects} project{p.max_projects === 1 ? "" : "s"}
                </span>
                <span>Server: {p.server_type}</span>
              </CardContent>
            </Card>
          );
        })}
      </div>
      <p className="text-sm text-muted-foreground">
        Self-service upgrades and billing aren&apos;t available yet; contact the platform team to change plans.
      </p>

      {account?.is_admin && <AdminSetPlan plans={plans} onChanged={load} />}
    </PageShell>
  );
}
