import { Switch, Route, Router as WouterRouter } from "wouter";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "@/components/ui/toaster";
import { TooltipProvider } from "@/components/ui/tooltip";

import { MigrationProvider } from "@/context/MigrationContext";
import { Shell } from "@/components/layout/Shell";

import Home from "@/pages/Home";
import Overview from "@/pages/Overview";
import ReviewMoves from "@/pages/ReviewMoves";
import Execute from "@/pages/Execute";
import NotFound from "@/pages/not-found";

const queryClient = new QueryClient();

function Router() {
  return (
    <Shell>
      <Switch>
        <Route path="/" component={Home} />
        <Route path="/overview" component={Overview} />
        <Route path="/review" component={ReviewMoves} />
        <Route path="/execute" component={Execute} />
        <Route component={NotFound} />
      </Switch>
    </Shell>
  );
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <MigrationProvider>
          <WouterRouter base={import.meta.env.BASE_URL.replace(/\/$/, "")}>
            <Router />
          </WouterRouter>
        </MigrationProvider>
        <Toaster />
      </TooltipProvider>
    </QueryClientProvider>
  );
}

export default App;
