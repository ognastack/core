"use client";

import * as React from "react";
import Link from "next/link";
import { IconCreditCard, IconInnerShadowTop, IconServer2 } from "@tabler/icons-react";

import { NavMain } from "@/components/nav-main";
import { NavUser } from "@/components/nav-user";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
import { useAuth } from "@/api/OgnaContext";

const NAV = [
  { title: "Projects", url: "/protected/projects", icon: IconServer2 },
  { title: "Plan & usage", url: "/protected/account", icon: IconCreditCard },
];

export function AppSidebar({ ...props }: React.ComponentProps<typeof Sidebar>) {
  const client = useAuth();
  const email = client.user?.email ?? "";
  const user = { name: email.split("@")[0] || "Account", email, avatar: "" };

  return (
    <Sidebar collapsible="offcanvas" {...props}>
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton asChild className="data-[slot=sidebar-menu-button]:!p-1.5">
              <Link href="/protected/projects">
                <IconInnerShadowTop className="!size-5" />
                <span className="text-base font-semibold">OGNA Platform</span>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>
      <SidebarContent>
        <NavMain items={NAV} />
      </SidebarContent>
      <SidebarFooter>
        <NavUser user={user} />
      </SidebarFooter>
    </Sidebar>
  );
}
