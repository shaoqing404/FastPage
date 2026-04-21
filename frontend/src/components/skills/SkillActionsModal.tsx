import React, { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { CopyPlus, Loader2, PencilLine, Trash2 } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

import { skillsApi } from '../../features/skills/api';
import { getErrorMessage } from '../../lib/utils';
import type { ChatSkill } from '../../types';
import { Field, InlineAlert, SurfaceModal } from '../ui/workbench';

const updateSkillListCache = (skills: ChatSkill[] | undefined, nextSkill: ChatSkill) => {
  if (!skills) return [nextSkill];
  const index = skills.findIndex((item) => item.id === nextSkill.id);
  if (index === -1) return [nextSkill, ...skills];
  const nextSkills = [...skills];
  nextSkills[index] = nextSkill;
  return nextSkills;
};

const removeSkillFromCache = (skills: ChatSkill[] | undefined, skillId: string) =>
  (skills || []).filter((item) => item.id !== skillId);

type SkillActionsModalProps = {
  open: boolean;
  skill: ChatSkill;
  onClose: () => void;
  onUpdated?: (skill: ChatSkill) => void;
  onDeleted?: () => void;
};

export const SkillActionsModal: React.FC<SkillActionsModalProps> = ({
  open,
  skill,
  onClose,
  onUpdated,
  onDeleted,
}) => {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [renameValue, setRenameValue] = useState(skill.name);
  const [copyName, setCopyName] = useState(`${skill.name} Copy`);
  const [renameFeedback, setRenameFeedback] = useState('');
  const [copyFeedback, setCopyFeedback] = useState('');
  const [deleteFeedback, setDeleteFeedback] = useState('');
  const [deleteConfirmValue, setDeleteConfirmValue] = useState('');

  const renameMutation = useMutation({
    mutationFn: async () => skillsApi.update(skill.id, { name: renameValue.trim() }),
    onSuccess: (updatedSkill) => {
      queryClient.setQueryData(['skill', skill.id], updatedSkill);
      queryClient.setQueryData<ChatSkill[] | undefined>(['skills'], (current) => updateSkillListCache(current, updatedSkill));
      queryClient.invalidateQueries({ queryKey: ['skills'] });
      setRenameFeedback('Skill name updated.');
      onUpdated?.(updatedSkill);
    },
    onError: (error: unknown) => {
      setRenameFeedback(getErrorMessage(error, 'Failed to rename skill'));
    },
  });

  const copyMutation = useMutation({
    mutationFn: async () => skillsApi.create({
      name: copyName.trim(),
      description: skill.description ?? null,
      system_prompt: skill.system_prompt,
      document_ids: skill.document_ids,
      knowledge_base_id: skill.knowledge_base_id ?? null,
      provider_id: skill.provider_id ?? null,
      model: skill.model,
      request_config: skill.request_config || {},
      conversation_config: skill.conversation_config || {},
      retrieval_config: skill.retrieval_config || {},
      generation_config: skill.generation_config || {},
      document_scope_type: skill.document_scope_type,
      visibility: skill.visibility,
    }),
    onSuccess: (copiedSkill) => {
      queryClient.invalidateQueries({ queryKey: ['skills'] });
      queryClient.setQueryData(['skill', copiedSkill.id], copiedSkill);
      navigate(`/skills/${copiedSkill.id}`);
      onClose();
    },
    onError: (error: unknown) => {
      setCopyFeedback(getErrorMessage(error, 'Failed to copy skill'));
    },
  });

  const deleteMutation = useMutation({
    mutationFn: async () => skillsApi.delete(skill.id),
    onSuccess: () => {
      queryClient.setQueryData<ChatSkill[] | undefined>(['skills'], (current) => removeSkillFromCache(current, skill.id));
      queryClient.invalidateQueries({ queryKey: ['skills'] });
      onDeleted?.();
      onClose();
    },
    onError: (error: unknown) => {
      setDeleteFeedback(getErrorMessage(error, 'Failed to delete skill'));
    },
  });

  const isDeleteConfirmed = deleteConfirmValue.trim() === skill.name;

  return (
    <SurfaceModal
      open={open}
      onClose={onClose}
      title="Skill actions"
      subtitle="Manage the saved configuration for this skill. Copy creates a new skill without any session history or run records."
      className="w-[760px]"
      bodyClassName="space-y-6"
    >
      <div className="grid gap-6 lg:grid-cols-2">
        <div className="space-y-4 rounded-[24px] border border-white/80 bg-white/62 p-5">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-blue-50 text-blue-600">
              <PencilLine size={18} />
            </div>
            <div>
              <p className="text-sm font-semibold text-slate-900">Rename skill</p>
              <p className="text-sm text-slate-500">Update the saved skill name without leaving this page.</p>
            </div>
          </div>
          <Field label="Skill name" required>
            <input
              className="field"
              value={renameValue}
              onChange={(event) => {
                setRenameValue(event.target.value);
                setRenameFeedback('');
              }}
            />
          </Field>
          {renameFeedback && (
            <InlineAlert tone={renameMutation.isError ? 'danger' : 'success'} title={renameMutation.isError ? 'Rename failed' : 'Renamed'}>
              {renameFeedback}
            </InlineAlert>
          )}
          <button
            type="button"
            className="btn-primary w-full justify-center"
            disabled={renameMutation.isPending || !renameValue.trim() || renameValue.trim() === skill.name}
            onClick={() => renameMutation.mutate()}
          >
            {renameMutation.isPending ? <Loader2 size={16} className="animate-spin" /> : <PencilLine size={16} />}
            <span>{renameMutation.isPending ? 'Saving…' : 'Save name'}</span>
          </button>
        </div>

        <div className="space-y-4 rounded-[24px] border border-white/80 bg-white/62 p-5">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-blue-50 text-blue-600">
              <CopyPlus size={18} />
            </div>
            <div>
              <p className="text-sm font-semibold text-slate-900">Copy skill</p>
              <p className="text-sm text-slate-500">Create a new skill from the current saved configuration only.</p>
            </div>
          </div>
          <Field label="New skill name" required>
            <input
              className="field"
              value={copyName}
              onChange={(event) => {
                setCopyName(event.target.value);
                setCopyFeedback('');
              }}
            />
          </Field>
          <InlineAlert tone="default" title="Copy boundary">
            Sessions, run history, telemetry, and any unsaved draft edits are not copied into the new skill.
          </InlineAlert>
          {copyFeedback && (
            <InlineAlert tone="danger" title="Copy failed">
              {copyFeedback}
            </InlineAlert>
          )}
          <button
            type="button"
            className="btn-primary w-full justify-center"
            disabled={copyMutation.isPending || !copyName.trim()}
            onClick={() => copyMutation.mutate()}
          >
            {copyMutation.isPending ? <Loader2 size={16} className="animate-spin" /> : <CopyPlus size={16} />}
            <span>{copyMutation.isPending ? 'Creating copy…' : 'Create copied skill'}</span>
          </button>
        </div>
      </div>

      <div className="space-y-4 rounded-[24px] border border-red-200/70 bg-red-50/60 p-5">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-red-100 text-red-600">
            <Trash2 size={18} />
          </div>
          <div>
            <p className="text-sm font-semibold text-slate-900">Delete skill</p>
            <p className="text-sm text-slate-500">This removes the skill itself. The action is not presented as recoverable here.</p>
          </div>
        </div>
        <Field label={`Type "${skill.name}" to confirm`} required>
          <input
            className="field"
            value={deleteConfirmValue}
            onChange={(event) => {
              setDeleteConfirmValue(event.target.value);
              setDeleteFeedback('');
            }}
          />
        </Field>
        {deleteFeedback && (
          <InlineAlert tone="danger" title="Delete failed">
            {deleteFeedback}
          </InlineAlert>
        )}
        <button
          type="button"
          className="btn-ghost w-full justify-center text-red-600"
          disabled={deleteMutation.isPending || !isDeleteConfirmed}
          onClick={() => deleteMutation.mutate()}
        >
          {deleteMutation.isPending ? <Loader2 size={16} className="animate-spin" /> : <Trash2 size={16} />}
          <span>{deleteMutation.isPending ? 'Deleting…' : 'Delete skill'}</span>
        </button>
      </div>
    </SurfaceModal>
  );
};
