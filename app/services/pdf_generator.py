# app/services/pdf_generator.py - PDF报告生成服务
from reportlab.lib.pagesizes import A4, letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch, cm
from reportlab.lib import colors
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
import io
import base64
from PIL import Image as PILImage, ImageDraw, ImageFont
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any
import logging
import qrcode

from app.schemas.approval import ExperimentDataItem, PDFGenerationConfig

logger = logging.getLogger(__name__)

class PDFGenerator:
    """PDF报告生成器"""
    
    def __init__(self):
        self.output_dir = Path("Data/approval/reports")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # 默认配置
        self.config = PDFGenerationConfig()
        
        # 样式
        self.styles = getSampleStyleSheet()
        self._setup_custom_styles()
        
        logger.info("PDF生成器已初始化")
    
    def _setup_custom_styles(self):
        """设置自定义样式"""
        # 标题样式
        self.title_style = ParagraphStyle(
            'CustomTitle',
            parent=self.styles['Heading1'],
            fontSize=18,
            spaceAfter=30,
            alignment=TA_CENTER,
            textColor=colors.darkblue
        )
        
        # 副标题样式
        self.subtitle_style = ParagraphStyle(
            'CustomSubtitle',
            parent=self.styles['Heading2'],
            fontSize=14,
            spaceAfter=20,
            textColor=colors.darkgreen
        )
        
        # 正文样式
        self.body_style = ParagraphStyle(
            'CustomBody',
            parent=self.styles['Normal'],
            fontSize=12,
            spaceAfter=12,
            leading=18
        )
        
        # 水印样式
        self.watermark_style = ParagraphStyle(
            'Watermark',
            parent=self.styles['Normal'],
            fontSize=10,
            textColor=colors.lightgrey,
            alignment=TA_CENTER
        )
    
    async def generate_report_pdf(
        self,
        report_id: str,
        title: str,
        content: str,
        experiment_data: Optional[List[ExperimentDataItem]] = None,
        operator: str = "",
        config: Optional[PDFGenerationConfig] = None
    ) -> Path:
        """
        生成实验报告PDF
        
        Args:
            report_id: 报告ID
            title: 报告标题
            content: 报告内容
            experiment_data: 实验数据
            operator: 操作员
            config: PDF生成配置
        
        Returns:
            生成的PDF文件路径
        """
        try:
            # 使用传入的配置或默认配置
            pdf_config = config or self.config
            
            # 生成文件路径
            filename = f"report_{report_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
            pdf_path = self.output_dir / filename
            
            logger.info(f"开始生成PDF报告: {pdf_path}")
            
            # 创建PDF文档
            doc = SimpleDocTemplate(
                str(pdf_path),
                pagesize=A4,
                rightMargin=pdf_config.margins["right"],
                leftMargin=pdf_config.margins["left"],
                topMargin=pdf_config.margins["top"],
                bottomMargin=pdf_config.margins["bottom"]
            )
            
            # 构建内容
            story = []
            
            # 添加水印和页眉
            story.extend(self._build_header(report_id, pdf_config))
            
            # 添加标题
            story.append(Paragraph(title, self.title_style))
            story.append(Spacer(1, 20))
            
            # 添加报告信息表
            story.extend(self._build_report_info(report_id, operator, pdf_config))
            story.append(Spacer(1, 20))
            
            # 添加内容
            story.append(Paragraph("实验内容", self.subtitle_style))
            story.append(Paragraph(content, self.body_style))
            story.append(Spacer(1, 20))
            
            # 添加实验数据表格
            if experiment_data:
                story.extend(self._build_data_table(experiment_data))
                story.append(Spacer(1, 20))
            
            # 添加二维码（如果启用）
            if pdf_config.include_qr_code:
                story.extend(self._build_qr_code(report_id))
                story.append(Spacer(1, 20))
            
            # 添加页脚信息
            story.extend(self._build_footer(pdf_config))
            
            # 构建PDF
            doc.build(story, onFirstPage=self._add_watermark, onLaterPages=self._add_watermark)
            
            logger.info(f"PDF报告生成完成: {pdf_path}")
            
            return pdf_path
            
        except Exception as e:
            logger.error(f"生成PDF报告失败: {e}")
            raise
    
    def _build_header(self, report_id: str, config: PDFGenerationConfig) -> List:
        """构建页眉"""
        elements = []
        
        # 水印文本
        watermark_text = f"🔒 {config.watermark_text}"
        elements.append(Paragraph(watermark_text, self.watermark_style))
        elements.append(Spacer(1, 10))
        
        # 时间戳
        if config.include_timestamp:
            timestamp = datetime.now().strftime("%Y年%m月%d日 %H:%M:%S")
            timestamp_text = f"生成时间: {timestamp}"
            elements.append(Paragraph(timestamp_text, self.watermark_style))
            elements.append(Spacer(1, 20))
        
        return elements
    
    def _build_report_info(self, report_id: str, operator: str, config: PDFGenerationConfig) -> List:
        """构建报告信息表"""
        elements = []
        
        # 报告信息数据
        data = [
            ['报告编号:', report_id],
            ['操作员:', operator],
            ['生成时间:', datetime.now().strftime("%Y年%m月%d日 %H:%M:%S")],
            ['状态:', '待审批']
        ]
        
        # 创建表格
        table = Table(data, colWidths=[2*inch, 4*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
            ('BACKGROUND', (1, 0), (1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        
        elements.append(table)
        return elements
    
    def _build_data_table(self, experiment_data: List[ExperimentDataItem]) -> List:
        """构建实验数据表格"""
        elements = []
        
        elements.append(Paragraph("实验数据", self.subtitle_style))
        
        # 表格数据
        data = [['参数名称', '数值', '单位', '说明']]  # 表头
        
        for item in experiment_data:
            data.append([
                item.parameter_name,
                item.value,
                item.unit or '-',
                item.description or '-'
            ])
        
        # 创建表格
        table = Table(data, colWidths=[2*inch, 1.5*inch, 1*inch, 2.5*inch])
        table.setStyle(TableStyle([
            # 表头样式
            ('BACKGROUND', (0, 0), (-1, 0), colors.darkblue),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            
            # 数据行样式
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
            
            # 网格
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            
            # 交替行背景
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.beige, colors.lightgrey])
        ]))
        
        elements.append(table)
        return elements
    
    def _build_qr_code(self, report_id: str) -> List:
        """构建二维码"""
        elements = []
        
        try:
            # 生成二维码
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_L,
                box_size=10,
                border=4,
            )
            qr.add_data(f"TIANMU_REPORT_{report_id}")
            qr.make(fit=True)
            
            # 创建二维码图像
            qr_img = qr.make_image(fill_color="black", back_color="white")
            
            # 保存到内存
            img_buffer = io.BytesIO()
            qr_img.save(img_buffer, format='PNG')
            img_buffer.seek(0)
            
            # 添加到PDF
            elements.append(Paragraph("报告二维码", self.subtitle_style))
            
            # 创建Image对象
            qr_image = Image(img_buffer, width=1.5*inch, height=1.5*inch)
            elements.append(qr_image)
            
        except Exception as e:
            logger.warning(f"生成二维码失败: {e}")
            elements.append(Paragraph("二维码生成失败", self.body_style))
        
        return elements
    
    def _build_footer(self, config: PDFGenerationConfig) -> List:
        """构建页脚"""
        elements = []
        
        elements.append(Spacer(1, 30))
        
        # 分隔线
        elements.append(Paragraph("_" * 80, self.watermark_style))
        elements.append(Spacer(1, 10))
        
        # 页脚信息
        footer_info = [
            "⚠️ 重要提示：",
            "• 本报告仅用于内部审批流程",
            "• 未经授权不得外传或复制",
            "• 审批链接仅在局域网内有效",
            "• 如有疑问请联系系统管理员"
        ]
        
        for info in footer_info:
            elements.append(Paragraph(info, self.watermark_style))
        
        elements.append(Spacer(1, 10))
        elements.append(Paragraph(f"TianMu工业AGI试验台 · 实验审批系统", self.watermark_style))
        
        return elements
    
    def _add_watermark(self, canvas, doc):
        """添加水印到每一页"""
        canvas.saveState()
        
        # 设置水印文本
        watermark_text = "TianMu实验报告 · 内部审批专用"
        
        # 计算页面中心位置
        page_width, page_height = A4
        
        # 设置水印样式
        canvas.setFont("Helvetica", 50)
        canvas.setFillColorRGB(0.9, 0.9, 0.9, alpha=0.3)
        
        # 旋转并绘制水印
        canvas.rotate(45)
        canvas.drawCentredText(page_width/2, page_height/4, watermark_text)
        
        # 页码
        canvas.setFont("Helvetica", 9)
        canvas.setFillColorRGB(0.5, 0.5, 0.5)
        page_num = canvas.getPageNumber()
        canvas.drawRightString(page_width - 30, 30, f"第 {page_num} 页")
        
        canvas.restoreState()
    
    async def generate_approval_summary_pdf(
        self,
        approval_records: List,
        title: str = "审批汇总报告"
    ) -> Path:
        """
        生成审批汇总报告PDF
        
        Args:
            approval_records: 审批记录列表
            title: 汇总报告标题
        
        Returns:
            生成的PDF文件路径
        """
        try:
            # 生成文件路径
            filename = f"approval_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
            pdf_path = self.output_dir / filename
            
            logger.info(f"开始生成审批汇总PDF: {pdf_path}")
            
            # 创建PDF文档
            doc = SimpleDocTemplate(str(pdf_path), pagesize=A4)
            
            # 构建内容
            story = []
            
            # 标题
            story.append(Paragraph(title, self.title_style))
            story.append(Spacer(1, 20))
            
            # 生成时间
            generation_time = datetime.now().strftime("%Y年%m月%d日 %H:%M:%S")
            story.append(Paragraph(f"生成时间: {generation_time}", self.body_style))
            story.append(Spacer(1, 20))
            
            # 汇总表格
            if approval_records:
                # 表格数据
                data = [['报告ID', '标题', '操作员', '审批人', '状态', '创建时间']]  # 表头
                
                for record in approval_records:
                    data.append([
                        record.report_id,
                        record.title[:30] + "..." if len(record.title) > 30 else record.title,
                        record.operator,
                        record.approver_email,
                        record.status.value,
                        record.created_at.strftime("%m-%d %H:%M")
                    ])
                
                # 创建表格
                table = Table(data, colWidths=[1.2*inch, 2.5*inch, 1*inch, 1.8*inch, 0.8*inch, 1*inch])
                table.setStyle(TableStyle([
                    # 表头样式
                    ('BACKGROUND', (0, 0), (-1, 0), colors.darkblue),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                    ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, 0), 10),
                    
                    # 数据行样式
                    ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                    ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
                    ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
                    ('FONTSIZE', (0, 1), (-1, -1), 8),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
                    
                    # 网格
                    ('GRID', (0, 0), (-1, -1), 1, colors.black),
                    
                    # 交替行背景
                    ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.beige, colors.lightgrey])
                ]))
                
                story.append(table)
            else:
                story.append(Paragraph("暂无审批记录", self.body_style))
            
            story.append(Spacer(1, 30))
            
            # 统计信息
            total_count = len(approval_records)
            pending_count = len([r for r in approval_records if r.status.value == 'pending'])
            approved_count = len([r for r in approval_records if r.status.value == 'approved'])
            rejected_count = len([r for r in approval_records if r.status.value == 'rejected'])
            
            stats_data = [
                ['统计项目', '数量'],
                ['总记录数', str(total_count)],
                ['待审批', str(pending_count)],
                ['已通过', str(approved_count)],
                ['已驳回', str(rejected_count)]
            ]
            
            stats_table = Table(stats_data, colWidths=[2*inch, 1*inch])
            stats_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.darkgreen),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 12),
                ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 1), (-1, -1), 10),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('BACKGROUND', (0, 1), (-1, -1), colors.lightgreen)
            ]))
            
            story.append(Paragraph("统计信息", self.subtitle_style))
            story.append(stats_table)
            
            # 构建PDF
            doc.build(story, onFirstPage=self._add_watermark, onLaterPages=self._add_watermark)
            
            logger.info(f"审批汇总PDF生成完成: {pdf_path}")
            
            return pdf_path
            
        except Exception as e:
            logger.error(f"生成审批汇总PDF失败: {e}")
            raise
    
    def get_pdf_file_size(self, pdf_path: Path) -> int:
        """获取PDF文件大小"""
        try:
            if pdf_path.exists():
                return pdf_path.stat().st_size
            return 0
        except Exception as e:
            logger.error(f"获取PDF文件大小失败: {e}")
            return 0
    
    def cleanup_old_pdfs(self, days: int = 30) -> int:
        """清理旧的PDF文件"""
        try:
            cutoff_time = datetime.now().timestamp() - (days * 24 * 3600)
            deleted_count = 0
            
            for pdf_file in self.output_dir.glob("*.pdf"):
                if pdf_file.stat().st_mtime < cutoff_time:
                    try:
                        pdf_file.unlink()
                        deleted_count += 1
                    except Exception as e:
                        logger.warning(f"删除PDF文件失败 {pdf_file}: {e}")
            
            logger.info(f"清理了 {deleted_count} 个旧PDF文件")
            return deleted_count
            
        except Exception as e:
            logger.error(f"清理旧PDF文件失败: {e}")
            return 0