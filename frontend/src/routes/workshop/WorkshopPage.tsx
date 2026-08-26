import { Route, Routes } from "react-router-dom";
import { CaseListPage } from "./CaseListPage";
import { CaseWizardPage } from "./CaseWizardPage";
import { TracePage } from "./TracePage";

export function WorkshopPage() {
  return (
    <Routes>
      <Route index element={<CaseListPage />} />
      <Route path=":caseId" element={<CaseWizardPage />} />
      <Route path=":caseId/trace" element={<TracePage />} />
    </Routes>
  );
}
