import { api } from "@/lib/api";
import { useToast } from "@/lib/toast";
import { navigate } from "@/lib/router";
import { Modal } from "@/components/ui/modal";
import { NovelForm } from "./novel-form";

export function NewNovelDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { toast } = useToast();
  return (
    <Modal open={open} onClose={onClose} title="New novel" className="max-w-xl">
      <NovelForm
        saveLabel="Create the novel"
        onSave={async (fields) => {
          if (!fields.title.trim()) return toast("Give the novel a title", "error");
          try {
            const novel = await api.createNovel(fields);
            onClose();
            navigate(`/n/${novel.id}`);
          } catch (e) {
            toast(e instanceof Error ? e.message : String(e), "error");
          }
        }}
      />
    </Modal>
  );
}
