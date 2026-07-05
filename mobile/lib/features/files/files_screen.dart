import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/websocket_client.dart';

class FilesScreen extends ConsumerStatefulWidget {
  const FilesScreen({super.key});

  @override
  ConsumerState<FilesScreen> createState() => _FilesScreenState();
}

class _FilesScreenState extends ConsumerState<FilesScreen> {
  String _currentPath = r'C:\';
  List<Map<String, dynamic>> _entries = [];
  bool _loading = false;

  @override
  void initState() {
    super.initState();
    _load(_currentPath);
  }

  Future<void> _load(String path) async {
    setState(() => _loading = true);
    try {
      final client = ref.read(mobpcClientProvider);
      final resp = await client.send('file.list', payload: {'path': path});
      if (resp.ok && resp.data != null) {
        setState(() {
          _currentPath = resp.data!['path'] as String? ?? path;
          _entries = (resp.data!['entries'] as List<dynamic>)
              .map((e) => e as Map<String, dynamic>)
              .toList();
        });
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Ошибка: $e')),
        );
      }
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  void _goUp() {
    final parts = _currentPath.split(r'\').where((p) => p.isNotEmpty).toList();
    if (parts.length <= 1) return;
    parts.removeLast();
    final parent = parts.join(r'\');
    _load('$parent\\');
  }

  Future<void> _delete(String name) async {
    final path = '$_currentPath$name';
    final confirm = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('Удалить?'),
        content: Text(path),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Нет')),
          TextButton(onPressed: () => Navigator.pop(context, true), child: const Text('Да')),
        ],
      ),
    );
    if (confirm != true) return;
    final client = ref.read(mobpcClientProvider);
    await client.send('file.delete', payload: {'path': path, 'dangerous': true});
    _load(_currentPath);
  }

  String _formatSize(int bytes) {
    if (bytes < 1024) return '$bytes B';
    if (bytes < 1024 * 1024) return '${(bytes / 1024).toStringAsFixed(1)} KB';
    return '${(bytes / (1024 * 1024)).toStringAsFixed(1)} MB';
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Файлы'),
        actions: [
          IconButton(icon: const Icon(Icons.arrow_upward), onPressed: _goUp),
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: _loading ? null : () => _load(_currentPath),
          ),
        ],
      ),
      body: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.all(12),
            child: Text(_currentPath, style: const TextStyle(fontSize: 12)),
          ),
          Expanded(
            child: _loading
                ? const Center(child: CircularProgressIndicator())
                : ListView.builder(
                    itemCount: _entries.length,
                    itemBuilder: (context, index) {
                      final entry = _entries[index];
                      final name = entry['name'] as String;
                      final isDir = entry['is_dir'] as bool? ?? false;
                      final size = entry['size'] as int? ?? 0;
                      return ListTile(
                        leading: Icon(isDir ? Icons.folder : Icons.insert_drive_file),
                        title: Text(name),
                        subtitle: isDir ? null : Text(_formatSize(size)),
                        onTap: () {
                          if (isDir) {
                            _load('$_currentPath$name\\');
                          }
                        },
                        trailing: IconButton(
                          icon: const Icon(Icons.delete_outline),
                          onPressed: () => _delete(name),
                        ),
                      );
                    },
                  ),
          ),
        ],
      ),
    );
  }
}
