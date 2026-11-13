import { redirect } from "next/navigation";

export default function ProtectedIndex() {
  redirect("/protected/projects");
}
