import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mobile_scanner/mobile_scanner.dart';

import '../../core/profile_storage.dart';
import '../../core/protocol.dart';
import '../../core/websocket_client.dart';
import '../remote/remote_screen.dart';

class HomeScreen extends ConsumerWidget {
  const HomeScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final profiles = ref.watch(profilesProvider);
    return Scaffold(
      appBar: AppBar(
        title: const Text('mobpc'),
        actions: [
          IconButton(
            icon: const Icon(Icons.qr_code_scanner),
            onPressed: () => Navigator.push(
              context,
              MaterialPageRoute(builder: (_) => const PairingScreen()),
            ),
          ),
        ],
      ),
      body: profiles.isEmpty
          ? const Center(
              child: Text('Нет подключённых ПК.\nНажмите QR для привязки.'),
            )
          : ListView.builder(
              itemCount: profiles.length,
              itemBuilder: (context, index) {
                final profile = profiles[index];
                return ListTile(
                  leading: const Icon(Icons.computer),
                  title: Text(profile.name),
                  subtitle: Text('${profile.host}:${profile.port}'),
                  onTap: () => _connect(context, ref, profile),
                );
              },
            ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () => Navigator.push(
          context,
          MaterialPageRoute(builder: (_) => const ManualPairingScreen()),
        ),
        icon: const Icon(Icons.add),
        label: const Text('Добавить ПК'),
      ),
    );
  }

  Future<void> _connect(
    BuildContext context,
    WidgetRef ref,
    ConnectionProfile profile,
  ) async {
    final client = ref.read(mobpcClientProvider);
    try {
      await client.connect(profile, autoReconnect: true);
      if (!context.mounted) return;
      Navigator.push(
        context,
        MaterialPageRoute(builder: (_) => const RemoteScreen()),
      );
    } catch (e) {
      if (!context.mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Ошибка подключения: $e')),
      );
    }
  }
}

class PairingScreen extends ConsumerStatefulWidget {
  const PairingScreen({super.key});

  @override
  ConsumerState<PairingScreen> createState() => _PairingScreenState();
}

class _PairingScreenState extends ConsumerState<PairingScreen> {
  bool _processing = false;

  Future<void> _onDetect(BarcodeCapture capture) async {
    if (_processing) return;
    final raw = capture.barcodes.firstOrNull?.rawValue;
    if (raw == null) return;
    _processing = true;
    try {
      final payload = PairingPayload.tryParse(raw);
      if (payload == null) throw Exception('Это не QR-код mobpc');
      final profile = await exchangePairingCode(
        host: payload.host,
        port: payload.port,
        code: payload.code,
      );
      await ref.read(profilesProvider.notifier).add(profile);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('ПК привязан!')),
      );
      Navigator.pop(context);
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Ошибка: $e')),
      );
    } finally {
      _processing = false;
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Сканировать QR')),
      body: MobileScanner(onDetect: _onDetect),
    );
  }
}

class ManualPairingScreen extends ConsumerStatefulWidget {
  const ManualPairingScreen({super.key});

  @override
  ConsumerState<ManualPairingScreen> createState() =>
      _ManualPairingScreenState();
}

class _ManualPairingScreenState extends ConsumerState<ManualPairingScreen> {
  final _hostCtrl = TextEditingController(text: '100.');
  final _portCtrl = TextEditingController(text: '8765');
  final _codeCtrl = TextEditingController();
  final _nameCtrl = TextEditingController(text: 'My PC');
  bool _useTls = false;
  bool _loading = false;

  @override
  void dispose() {
    _hostCtrl.dispose();
    _portCtrl.dispose();
    _codeCtrl.dispose();
    _nameCtrl.dispose();
    super.dispose();
  }

  Future<void> _pair() async {
    setState(() => _loading = true);
    try {
      final profile = await exchangePairingCode(
        host: _hostCtrl.text.trim(),
        port: int.parse(_portCtrl.text.trim()),
        code: _codeCtrl.text.trim(),
        deviceName: _nameCtrl.text.trim(),
        useTls: _useTls,
      );
      await ref.read(profilesProvider.notifier).add(profile);
      if (!mounted) return;
      Navigator.pop(context);
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Ошибка: $e')),
      );
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Ручная привязка')),
      body: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          children: [
            TextField(
              controller: _nameCtrl,
              decoration: const InputDecoration(labelText: 'Имя ПК'),
            ),
            TextField(
              controller: _hostCtrl,
              decoration: const InputDecoration(
                labelText: 'Host (Tailscale IP)',
              ),
            ),
            TextField(
              controller: _portCtrl,
              decoration: const InputDecoration(labelText: 'Порт'),
              keyboardType: TextInputType.number,
            ),
            TextField(
              controller: _codeCtrl,
              decoration: const InputDecoration(labelText: 'Код привязки'),
            ),
            SwitchListTile(
              title: const Text('TLS (WSS)'),
              value: _useTls,
              onChanged: (v) => setState(() => _useTls = v),
            ),
            const SizedBox(height: 16),
            FilledButton(
              onPressed: _loading ? null : _pair,
              child: _loading
                  ? const CircularProgressIndicator()
                  : const Text('Привязать'),
            ),
          ],
        ),
      ),
    );
  }
}
