// SPDX-FileCopyrightText: Copyright (c) 2025 KX Systems, Inc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
// http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

import { useState, useRef } from 'react';
import { X, Upload, File, Trash2, CheckCircle } from 'lucide-react';
import { clsx } from 'clsx';
import { Button } from '../common';
import { uploadDocuments } from '../../api/collections';

interface FileUploadDialogProps {
  isOpen: boolean;
  collectionName: string;
  onClose: () => void;
  onUploaded: () => void;
}

export function FileUploadDialog({ isOpen, collectionName, onClose, onUploaded }: FileUploadDialogProps) {
  const [files, setFiles] = useState<File[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadComplete, setUploadComplete] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFiles = Array.from(e.target.files || []);
    setFiles(prev => [...prev, ...selectedFiles]);
    setError(null);
    setUploadComplete(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    const droppedFiles = Array.from(e.dataTransfer.files);
    setFiles(prev => [...prev, ...droppedFiles]);
    setError(null);
    setUploadComplete(false);
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
  };

  const removeFile = (index: number) => {
    setFiles(prev => prev.filter((_, i) => i !== index));
  };

  const handleUpload = async () => {
    if (files.length === 0) return;

    setIsUploading(true);
    setError(null);

    try {
      await uploadDocuments(collectionName, files);
      setUploadComplete(true);
      setFiles([]);
      onUploaded();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to upload files');
    } finally {
      setIsUploading(false);
    }
  };

  const handleClose = () => {
    if (!isUploading) {
      setFiles([]);
      setError(null);
      setUploadComplete(false);
      onClose();
    }
  };

  const formatFileSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-nvidia-gray-800 rounded-xl border border-nvidia-gray-700 w-full max-w-lg shadow-2xl animate-fade-in">
        <div className="flex items-center justify-between p-4 border-b border-nvidia-gray-700">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-nvidia-green/20 flex items-center justify-center">
              <Upload className="w-5 h-5 text-nvidia-green" />
            </div>
            <div>
              <h3 className="text-lg font-semibold text-white">Upload Documents</h3>
              <p className="text-sm text-nvidia-gray-400">to {collectionName}</p>
            </div>
          </div>
          <button
            onClick={handleClose}
            disabled={isUploading}
            className="p-1 text-nvidia-gray-400 hover:text-white transition-colors disabled:opacity-50"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-4 space-y-4">
          {/* Drop zone */}
          <div
            onDrop={handleDrop}
            onDragOver={handleDragOver}
            onClick={() => fileInputRef.current?.click()}
            className={clsx(
              'border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-colors',
              'hover:border-nvidia-green hover:bg-nvidia-green/5',
              isUploading ? 'pointer-events-none opacity-50' : 'border-nvidia-gray-600'
            )}
          >
            <Upload className="w-10 h-10 text-nvidia-gray-500 mx-auto mb-3" />
            <p className="text-nvidia-gray-300 font-medium">
              Drop files here or click to browse
            </p>
            <p className="text-sm text-nvidia-gray-500 mt-1">
              Supports PDF, DOCX, TXT, MD, RTF files
            </p>
          </div>

          <input
            ref={fileInputRef}
            type="file"
            multiple
            onChange={handleFileSelect}
            className="hidden"
            accept=".rtf,.pdf,.docx,.doc,.md,.txt"
          />

          {/* File list */}
          {files.length > 0 && (
            <div className="space-y-2 max-h-48 overflow-y-auto scrollbar-thin">
              {files.map((file, index) => (
                <div
                  key={index}
                  className="flex items-center justify-between p-3 bg-nvidia-gray-700/50 rounded-lg"
                >
                  <div className="flex items-center gap-3 min-w-0">
                    <File className="w-4 h-4 text-nvidia-gray-400 flex-shrink-0" />
                    <div className="min-w-0">
                      <p className="text-sm text-white truncate">{file.name}</p>
                      <p className="text-xs text-nvidia-gray-500">{formatFileSize(file.size)}</p>
                    </div>
                  </div>
                  <button
                    onClick={() => removeFile(index)}
                    disabled={isUploading}
                    className="p-1 text-nvidia-gray-400 hover:text-red-400 transition-colors disabled:opacity-50"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              ))}
            </div>
          )}

          {/* Success message */}
          {uploadComplete && (
            <div className="flex items-center gap-3 bg-nvidia-green/10 border border-nvidia-green/30 rounded-lg p-3">
              <CheckCircle className="w-5 h-5 text-nvidia-green flex-shrink-0" />
              <p className="text-sm text-nvidia-green">Files uploaded successfully!</p>
            </div>
          )}

          {/* Error message */}
          {error && (
            <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-3">
              <p className="text-sm text-red-400">{error}</p>
            </div>
          )}

          <div className="flex justify-end gap-2 pt-2">
            <Button variant="ghost" onClick={handleClose} disabled={isUploading}>
              {uploadComplete ? 'Done' : 'Cancel'}
            </Button>
            {!uploadComplete && (
              <Button
                onClick={handleUpload}
                disabled={files.length === 0 || isUploading}
                isLoading={isUploading}
              >
                Upload {files.length > 0 && `(${files.length})`}
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
