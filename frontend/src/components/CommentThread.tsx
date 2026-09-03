import { useEffect, useState } from 'react'
import { createComment, deleteComment, fetchComments, updateComment } from '../api'
import { useAuth } from '../auth/AuthContext'
import type { Comment as CommentType } from '../types'

interface Props {
  workspaceId: number
  entryId: number
  entryOwnerId: number
}

function insertReply(comments: CommentType[], parentId: number, reply: CommentType): CommentType[] {
  return comments.map((c) =>
    c.id === parentId
      ? { ...c, replies: [...c.replies, reply] }
      : { ...c, replies: insertReply(c.replies, parentId, reply) },
  )
}

function replaceComment(comments: CommentType[], updated: CommentType): CommentType[] {
  return comments.map((c) =>
    c.id === updated.id ? { ...updated, replies: c.replies } : { ...c, replies: replaceComment(c.replies, updated) },
  )
}

function removeComment(comments: CommentType[], commentId: number): CommentType[] {
  return comments.filter((c) => c.id !== commentId).map((c) => ({ ...c, replies: removeComment(c.replies, commentId) }))
}

function countComments(comments: CommentType[]): number {
  return comments.reduce((sum, c) => sum + 1 + countComments(c.replies), 0)
}

export default function CommentThread({ workspaceId, entryId, entryOwnerId }: Props) {
  const { user, token } = useAuth()
  const [expanded, setExpanded] = useState(false)
  const [comments, setComments] = useState<CommentType[]>([])
  const [loading, setLoading] = useState(false)
  const [newBody, setNewBody] = useState('')
  const [posting, setPosting] = useState(false)
  const [totalCount, setTotalCount] = useState<number | null>(null)

  useEffect(() => {
    // Loaded once, up front (not gated behind "expanded"), purely so the
    // toggle button can show a comment count without requiring a click.
    fetchComments(workspaceId, entryId, token)
      .then((c) => setTotalCount(countComments(c)))
      .catch(() => setTotalCount(null))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspaceId, entryId])

  useEffect(() => {
    if (!expanded) return
    setLoading(true)
    fetchComments(workspaceId, entryId, token)
      .then(setComments)
      .finally(() => setLoading(false))
  }, [expanded, workspaceId, entryId, token])

  async function handlePostTopLevel(e: React.FormEvent) {
    e.preventDefault()
    if (!token || !newBody.trim()) return
    setPosting(true)
    try {
      const comment = await createComment(workspaceId, entryId, { body: newBody.trim() }, token)
      setComments((prev) => [...prev, comment])
      setTotalCount((prev) => (prev ?? 0) + 1)
      setNewBody('')
    } finally {
      setPosting(false)
    }
  }

  function handleReplyPosted(parentId: number, reply: CommentType) {
    setComments((prev) => insertReply(prev, parentId, reply))
    setTotalCount((prev) => (prev ?? 0) + 1)
  }

  function handleUpdated(updated: CommentType) {
    setComments((prev) => replaceComment(prev, updated))
  }

  function handleDeleted(commentId: number) {
    setComments((prev) => {
      const before = countComments(prev)
      const next = removeComment(prev, commentId)
      setTotalCount((count) => (count ?? 0) - (before - countComments(next)))
      return next
    })
  }

  return (
    <div className="comment-thread">
      <button type="button" className="link-btn" onClick={() => setExpanded((e) => !e)}>
        {expanded ? 'Hide comments' : `Comments${totalCount ? ` (${totalCount})` : ''}`}
      </button>

      {expanded && (
        <div className="comment-thread-body">
          {loading && <p className="hint">Loading comments...</p>}
          {!loading && comments.length === 0 && <p className="hint">No comments yet.</p>}

          {comments.length > 0 && (
            <ul className="comment-list">
              {comments.map((comment) => (
                <CommentItem
                  key={comment.id}
                  comment={comment}
                  workspaceId={workspaceId}
                  entryOwnerId={entryOwnerId}
                  onReplyPosted={handleReplyPosted}
                  onUpdated={handleUpdated}
                  onDeleted={handleDeleted}
                />
              ))}
            </ul>
          )}

          {user && (
            <form className="comment-form" onSubmit={handlePostTopLevel}>
              <textarea
                rows={2}
                placeholder="Add a comment..."
                value={newBody}
                onChange={(e) => setNewBody(e.target.value)}
              />
              <button type="submit" disabled={posting || !newBody.trim()}>
                {posting ? 'Posting...' : 'Post'}
              </button>
            </form>
          )}
        </div>
      )}
    </div>
  )
}

interface ItemProps {
  comment: CommentType
  workspaceId: number
  entryOwnerId: number
  onReplyPosted: (parentId: number, reply: CommentType) => void
  onUpdated: (updated: CommentType) => void
  onDeleted: (commentId: number) => void
}

function CommentItem({ comment, workspaceId, entryOwnerId, onReplyPosted, onUpdated, onDeleted }: ItemProps) {
  const { user, token } = useAuth()
  const [replying, setReplying] = useState(false)
  const [replyBody, setReplyBody] = useState('')
  const [posting, setPosting] = useState(false)
  const [editing, setEditing] = useState(false)
  const [editBody, setEditBody] = useState(comment.body)
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState(false)

  const isAuthor = user?.id === comment.author_id
  // Moderation power (delete only, not edit) belongs to the entry's
  // *primary* author specifically - the same extra power they already have
  // over visibility, co-authors, and entry deletion. A co-author who isn't
  // also the comment's author gets neither.
  const isEntryPrimaryAuthor = user?.id === entryOwnerId
  const canDelete = isAuthor || isEntryPrimaryAuthor

  async function submitReply(e: React.FormEvent) {
    e.preventDefault()
    if (!token || !replyBody.trim()) return
    setPosting(true)
    try {
      const reply = await createComment(
        workspaceId,
        comment.entry_id,
        { body: replyBody.trim(), parent_comment_id: comment.id },
        token,
      )
      onReplyPosted(comment.id, reply)
      setReplyBody('')
      setReplying(false)
    } finally {
      setPosting(false)
    }
  }

  async function saveEdit() {
    if (!token || !editBody.trim()) return
    setSaving(true)
    try {
      const updated = await updateComment(comment.id, editBody.trim(), token)
      onUpdated(updated)
      setEditing(false)
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete() {
    if (!token) return
    setDeleting(true)
    try {
      await deleteComment(comment.id, token)
      onDeleted(comment.id)
    } finally {
      setDeleting(false)
    }
  }

  return (
    <li className="comment-item">
      <div className="comment-meta">
        <strong>{comment.author_username}</strong>
        <span className="comment-time">{new Date(comment.created_at).toLocaleString()}</span>
        {comment.edited_at && <span className="comment-edited">(edited)</span>}
      </div>

      {editing ? (
        <div className="comment-edit">
          <textarea rows={2} value={editBody} onChange={(e) => setEditBody(e.target.value)} />
          <div className="comment-actions">
            <button type="button" onClick={saveEdit} disabled={saving || !editBody.trim()}>
              {saving ? 'Saving...' : 'Save'}
            </button>
            <button type="button" className="link-btn" onClick={() => setEditing(false)} disabled={saving}>
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <p className="comment-body">{comment.body}</p>
      )}

      {!editing && (
        <div className="comment-actions">
          {user && (
            <button type="button" className="link-btn" onClick={() => setReplying((r) => !r)}>
              Reply
            </button>
          )}
          {isAuthor && (
            <button type="button" className="link-btn" onClick={() => setEditing(true)}>
              Edit
            </button>
          )}
          {canDelete && (
            <button type="button" className="link-btn" onClick={handleDelete} disabled={deleting}>
              {deleting ? 'Deleting...' : 'Delete'}
            </button>
          )}
        </div>
      )}

      {replying && (
        <form className="comment-form comment-reply-form" onSubmit={submitReply}>
          <textarea
            rows={2}
            placeholder={`Reply to ${comment.author_username}...`}
            value={replyBody}
            onChange={(e) => setReplyBody(e.target.value)}
          />
          <button type="submit" disabled={posting || !replyBody.trim()}>
            {posting ? 'Posting...' : 'Reply'}
          </button>
        </form>
      )}

      {comment.replies.length > 0 && (
        <ul className="comment-list comment-replies">
          {comment.replies.map((reply) => (
            <CommentItem
              key={reply.id}
              comment={reply}
              workspaceId={workspaceId}
              entryOwnerId={entryOwnerId}
              onReplyPosted={onReplyPosted}
              onUpdated={onUpdated}
              onDeleted={onDeleted}
            />
          ))}
        </ul>
      )}
    </li>
  )
}
