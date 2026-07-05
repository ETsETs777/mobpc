import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/websocket_client.dart';

class TerminalScreen extends ConsumerStatefulWidget {
  const TerminalScreen({super.key});

  @override
  ConsumerState<TerminalScreen> createState() => _TerminalScreenState();
}

class _TerminalScreenState extends ConsumerState<TerminalScreen> {
  final _cmdCtrl = TextEditingController();
  final _outputCtrl = TextEditingController();
  final _scrollCtrl = ScrollController();
  String _shell = 'powershell';
  bool _running = false;

  @override
  void initState() {
    super.initState();
    final client = ref.read(mobpcClientProvider);
    client.events.listen(_onEvent);
  }

  void _onEvent(Map<String, dynamic> event) {
    if (event['type'] == 'shell.stream') {
      final data = event['data'] as Map<String, dynamic>?;
      final text = data?['data'] as String? ?? '';
      final stream = data?['stream'] as String? ?? '';
      final prefix = stream == 'stderr' ? '[ERR] ' : '';
      setState(() {
        _outputCtrl.text += '$prefix$text';
      });
      _scrollToBottom();
    }
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scrollCtrl.hasClients) {
        _scrollCtrl.jumpTo(_scrollCtrl.position.maxScrollExtent);
      }
    });
  }

  Future<void> _run() async {
    final cmd = _cmdCtrl.text.trim();
    if (cmd.isEmpty || _running) return;
    setState(() {
      _running = true;
      _outputCtrl.text += '\n> $cmd\n';
    });
    _scrollToBottom();
    try {
      final client = ref.read(mobpcClientProvider);
      final resp = await client.send(
        'shell.exec',
        payload: {'command': cmd, 'shell': _shell},
        timeout: const Duration(minutes: 5),
      );
      if (resp.ok && resp.data != null) {
        final exitCode = resp.data!['exit_code'];
        setState(() {
          _outputCtrl.text += '\n[exit: $exitCode]\n';
        });
      } else {
        setState(() {
          _outputCtrl.text += '\n[error: ${resp.error}]\n';
        });
      }
    } catch (e) {
      setState(() {
        _outputCtrl.text += '\n[error: $e]\n';
      });
    } finally {
      setState(() => _running = false);
      _scrollToBottom();
    }
  }

  @override
  void dispose() {
    _cmdCtrl.dispose();
    _outputCtrl.dispose();
    _scrollCtrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Терминал'),
        actions: [
          DropdownButton<String>(
            value: _shell,
            items: const [
              DropdownMenuItem(value: 'powershell', child: Text('PowerShell')),
              DropdownMenuItem(value: 'cmd', child: Text('CMD')),
            ],
            onChanged: _running
                ? null
                : (v) => setState(() => _shell = v ?? 'powershell'),
          ),
          IconButton(
            icon: const Icon(Icons.delete_outline),
            onPressed: () => setState(() => _outputCtrl.clear()),
          ),
        ],
      ),
      body: Column(
        children: [
          Expanded(
            child: SingleChildScrollView(
              controller: _scrollCtrl,
              padding: const EdgeInsets.all(12),
              child: Text(
                _outputCtrl.text.isEmpty
                    ? 'Введите команду ниже...'
                    : _outputCtrl.text,
                style: const TextStyle(
                  fontFamily: 'monospace',
                  fontSize: 13,
                ),
              ),
            ),
          ),
          Padding(
            padding: const EdgeInsets.all(8),
            child: Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _cmdCtrl,
                    decoration: const InputDecoration(
                      hintText: 'Команда...',
                      border: OutlineInputBorder(),
                    ),
                    onSubmitted: (_) => _run(),
                  ),
                ),
                const SizedBox(width: 8),
                FilledButton(
                  onPressed: _running ? null : _run,
                  child: _running
                      ? const SizedBox(
                          width: 20,
                          height: 20,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(Icons.play_arrow),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
