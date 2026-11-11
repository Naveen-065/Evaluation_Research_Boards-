//--------------------------------------------------------------------------------------------------
//  _  __  _       ___    _  __    ___  __   __  ___   _____   ___   __  __   ___
// | |/ / | |     / _ \  | |/ /   / __| \ \ / / / __| |_   _| | __| |  \/  | / __|
// | ' <  | |__  | (_) | | ' <    \__ \  \ V /  \__ \   | |   | _|  | |\/| | \__ \
// |_|\_\ |____|  \___/  |_|\_\   |___/   |_|   |___/   |_|   |___| |_|  |_| |___/
//
// This program is Confidential and Proprietary product of Klok Systems. Any unauthorized use,
// reproduction or transfer of this program is strictly prohibited unless written authorization
// from Klok Systems. (c) 2019 Klok Systems India Private Limited - All Rights Reserved
//--------------------------------------------------------------------------------------------------
// FILE NAME     : top_module
// AUTHOR        : Sindhu J S
//--------------------------------------------------------------------------------------------------
// Description: 
//
//
//--------------------------------------------------------------------------------------------------
import X1_pkg::*;
module top_module (
  // user clock and reset
  input                       i_user_clk          , 
  input                       i_user_rst          ,
  // wishbone clock and reset                     
  input                       i_wb_rst            ,
  input                       i_wb_clk            ,
  // Scan debug mode pins                         
  input                       i_scan_si1          , // scan input 
  input                       i_scan_se1          , // scan select
  input                       i_TM                , // Test mode enable (TM = 1 to enable , TM = 1 to disable )
  input [p_cnt_ints-1:0]      i_stop_bit          ,	// TDC stop bit  
  // mux select lines                       
  output [p_mux_sel-1:0]      o_mux_sel           , // mux select lines to select voltages across form , read, program set and reset
  // subtractor signlas                
  output wire                 o_ramp              , 
  output                      o_precharge         ,
  output                      o_v_count           ,
  output                      o_hold              ,   
  output                      o_start             , 	
  //output signals which will be connected as input signals to decoders   
  //Source line                           
  output [p_dec_len-1:0]      o_sl_float          , 
  output [p_dec_len-1:0]      o_sl_addr           , 
  output [p_dec_len-1:0]      o_sl_data           , 
  //Bit Line                      
  output [p_dec_len-1:0]      o_bl_addr           ,
  output [p_dec_len-1:0]      o_bl_data           , 
  output [p_dec_len-1:0]      o_bl_float          ,   
  //Word Line                      
  output [p_dec_len-1:0]      o_wl_float          , 
  output [p_dec_len-1:0]      o_wl_addr           ,
  output [p_dec_len-1:0]      o_wl_data           , // when test mode is enabled these pins are connected to decoder else pwm dac out is connected 
  // wishbone slave signals              
  input  [p_wbs_addr-1:0]     i_wbs_adr           , // Wishbone write address
  input  [p_wb_len-1:0]       i_wbs_dat           , // Wishbone Write data
  output                      o_wbs_ack           , // Wishbone acknowledgment
  input                       i_wbs_cyc           , // Wishbone cycle
  input                       i_wbs_stb           , // Wishbone strobe
  input                       i_wbs_we            , // Wishbone write/read enable (write = 1 , read = 0 )
  input  [p_wb_sel-1:0]       i_wbs_sel           , // Wishbone select 
  output [p_wb_len-1:0]       o_wbs_data          , // Wishbone read data
  output wire                 o_TM                , // TM output 
  // PWM DAC data and enable signal 
  output [p_pwm_isnts-1:0]    o_pwm_en            ,
  output [p_pwm_data_len-1:0] o_pwm_dac_outp [0:p_pwm_isnts-1] 
  
);
  wire         w_tdc_start                ; // TDC start 
  wire         w_tdc_vld                  ; // TDC valid
  wire         w_r_tdc_vld                ; // multiplexed TDC valid
  wire         w_spd_data_vld             ; // scartchpad data valid
  wire         w_read_done                ; // read done 
  wire         w_form_done                ; // forming done 
  wire         w_pgm_reset_done           ; // program reset done
  wire         w_pgm_set_done             ; // program set done
  reg          w_fifo_ren                 ; // fifo read enable
  wire         w_form_read_mode_en        ; // form read enable
  wire         w_pgm_reset_read_mode_en   ; // program reset read enable
  wire         w_pgm_set_read_mode_en     ; // program set read enable
  wire         w_read_en_spd              ; // read enable for scratch pad
  wire         w_tdc_rd_en                ; // tdc read enable
  wire         w_fsm_start                ;	// fsm start 
  reg          r_scan_word_valid          ; // scan word valid
  reg          r_in_progress              ; // represents shifting bits in progress
  wire         w_rd_full_row              ; // To read all cells in entire row 
  wire         w_WL_EN_L                  ; // word line latch enable 
  wire         w_SL_EN_L                  ; // source line latch enable
  wire         w_BL_EN_L                  ; // bit line latch enable
  reg          r_op_set_d                 ; // delayed op_set
  reg          r_op_set                   ; // op set to decide whether to set or reset 
  wire [p_tdc_len-1:0]       w_scratchpad_data_out      ; // scratch pad data output
  wire [p_res_len-1:0]       w_target_set1              ; // target set1 
  wire [p_res_len-1:0]       w_target_set2              ; // target set2 
  wire [p_res_len-1:0]       w_target_reset1            ; // target reset1 
  wire [p_res_len-1:0]       w_target_reset2            ; // target reset2 
  wire [p_mux_sel-1:0]       w_mux_sel_fsm              ; // mux select fro fsm decoder
  wire [p_mux_sel-1:0]       w_mux_sel                  ; // mux select
  wire [p_dec_len-1:0]       w_data_bl                  ; // BL data from scandebug 
  wire [p_dec_len-1:0]       w_data_sl                  ; // SL data from scandebug 
  wire [p_dec_len-1:0]       w_addr_bl                  ; // BL address 
  wire [p_dec_len-1:0]       w_addr_wl                  ; // WL address 
  wire [p_dec_len-1:0]       w_addr_sl                  ; // SL address  
  wire [p_dec_len-1:0]       w_float_wl                 ; // WL float 
  wire [p_dec_len-1:0]       w_float_sl                 ; // SL float
  wire [p_dec_len-1:0]       w_float_bl                 ; // BL float
  wire [p_dec_len-1:0]       w_WL_Float                 ; // WL float from scandebug
  wire [p_dec_len-1:0]       w_Data_wl                  ; // WL data from scandebug
  wire [p_dec_len-1:0]       w_WL_addr                  ; // WL addr from scandebug
  wire [p_dec_len-1:0]       w_BL_Float                 ; // BL float 
  wire [p_dec_len-1:0]       w_Data_bl                  ; // BL data
  wire [p_dec_len-1:0]       w_BL_addr                  ; // BL address 
  wire [p_dec_len-1:0]       w_SL_Float                 ; // SL float
  wire [p_dec_len-1:0]       w_Data_sl                  ; // SL data 
  wire [p_dec_len-1:0]       w_SL_addr                  ; // SL address
  wire [p_tdc_len-1 :0]      w_tdc_cnt                  ; // tdc count 
  wire [p_tdc_len-1 :0]      w_r_tdc_cnt                ; // multiplexed TDC count 
  reg  [p_dead_len-1:0]      r_dead_time_cnt            ; // dead time count 
  reg  [p_tm_ot_len-1:0]     r_time_out_cnt             ; // time out count 
  reg  [p_shift_len-1:0]     r_shift                    ; // shift register
  reg  [p_shift_len-1:0]     r_scan_word                ; // scan word 
  wire [p_cba_addr_len-1:0]    w_row_addr                 ; // row address 
  wire [p_cba_addr_len-1:0]    w_col_addr                 ; // column address
  wire [p_no_cyc_len-1:0]    w_no_of_clk_cycles         ; // number of clock cycles
  wire [p_no_cyc_len-1:0]    w_counter_value            ; // counter value
  wire [p_err_reg_len- 1:0]  w_err_reg                  ; // error register
  wire [p_pwm_data_len-1:0]  w_pwm_data                 ; // pwm data 
  reg  [p_pwm_data_len-1:0]  r_pwm_data                 ; // pwm data register
  wire [p_pwm_data_len-1:0]  w_prev_pwm_data            ; // pwm data stored read mode
  reg  [p_addr_bit_cba-1:0]  r_wl_sel                   ; // wl select - selects address of cell
  reg  [p_addr_bit_cba-1:0]  r_bl_sel                   ; // bl select - selects address of cell
  reg  [p_addr_bit_cba-1:0]  r_sl_sel                   ; // sl select - selects address of cell
  reg  [p_addr_bit_cba-1:0]  r_wl_sel_d                 ; // delayed wl select
  reg  [p_addr_bit_cba-1:0]  r_bl_sel_d                 ; // delayed bl select
  reg  [p_addr_bit_cba-1:0]  r_sl_sel_d                 ; // delayed sl select
  wire [p_addr_bit_cba-1:0]  w_row_addr_pwm             ; // row address of cross bar array
  wire [p_addr_bit_cba-1:0]  w_col_addr_pwm             ; // column address of cross bar array
  reg  [4:0]   r_bit_cnt                  ;
  reg  [2:0]   w_mode                   ;
  reg  [2:0]   fsm_cntrl_slg            ;
  wire [1:0]   fsm_cntrl                ;
  reg  [1:0]   i_fsm_cntrl              ;
  
  //----------------------------------------------------------------------------------
  // Test Mode (i_TM) signal multiplexing
  //
  // When Test Mode (i_TM) is asserted, all output control, data, address, and
  // floating signals are driven from the scandebug (test mode).
  // When Test Mode is deasserted, outputs are driven by the normal FSM-generated
  // functional signals.
  //----------------------------------------------------------------------------------      
  assign o_bl_data    = (i_TM) ? w_Data_bl   : w_data_bl    ;                     
  assign o_sl_data    = (i_TM) ? w_Data_sl   : w_data_sl    ;                    
  assign o_wl_data    = (i_TM) ? w_Data_wl   : 32'h0        ;                    
  assign o_bl_addr    = (i_TM) ? w_BL_addr   : w_addr_bl    ;                     
  assign o_wl_addr    = (i_TM) ? w_WL_addr   : w_addr_wl    ;                     
  assign o_sl_addr    = (i_TM) ? w_SL_addr   : w_addr_sl    ;                     
  assign o_wl_float   = (i_TM) ? w_WL_Float  : w_float_wl   ;                    
  assign o_sl_float   = (i_TM) ? w_SL_Float  : w_float_sl   ;                     
  assign o_bl_float   = (i_TM) ? w_BL_Float  : w_float_bl   ; 
  assign o_mux_sel    = (i_TM) ? w_mux_sel   : w_mux_sel_fsm; 
  //---------------------------------------------------------------------------------- 
  
  assign w_r_tdc_cnt    = (w_tdc_cnt) ? w_tdc_cnt : 32'b0;	
  assign w_r_tdc_vld    = (w_tdc_vld) ? w_tdc_vld : 1'b0 ;
  assign o_TM           = i_TM;
  assign w_tdc_rd_en    = 1;
  
  //-----------------------------------------------------------------------------------
  // Scan data capture logic (Test Mode)
  //
  // This block serially shifts scan input data (scan_si1) into a shift register
  // when Test Mode (i_TM) and scan select are enabled 
  // A scan transaction starts on the first scan clock and continues
  // until a complete word is captured.
  //------------------------------------------------------------------------------------
  always @(posedge i_user_clk) begin
    if (i_user_rst) begin
      r_shift           <= '0;
      r_bit_cnt         <= '0;
      r_in_progress     <= 1'b0;
      r_scan_word       <= '0;
      r_scan_word_valid <= 1'b0;
    end else begin
      r_scan_word_valid <= 1'b0;      
      if ((i_scan_se1 == 0 && i_TM == 0)) begin
        r_in_progress <= 1'b0;
        r_bit_cnt     <= '0;
      end else if(i_scan_se1 == 0 && i_TM == 1) begin
        r_shift <= {i_scan_si1, r_shift[15:1]};
        if (!r_in_progress) begin
          r_in_progress <= 1'b1;
          r_bit_cnt     <= 5'd0;       
        end else begin
          r_bit_cnt <= r_bit_cnt + 5'd1;
        end
        if (r_bit_cnt == 5'd16) begin
          r_scan_word       <= r_shift;
          r_scan_word_valid <= 1'b1;                  
          r_in_progress     <= 1'b0;                    
          r_bit_cnt         <= '0;
        end
      end
    end
  end
  //------------------------------------------------------------------------------------
  // Scan word decode 
  // This block decodes a valid 16-bit scan word to select address of cell and
  // mode of operation to be performed 
  //------------------------------------------------------------------------------------
	always @(posedge i_user_clk) begin  
    if(i_user_rst ) begin 
      r_op_set <= 'b0;
    end 	 
      if (r_scan_word_valid) begin
        r_op_set <= r_scan_word[15];      // bit 15
        r_sl_sel <= r_scan_word[14:10];   // bits 14..10
        r_bl_sel <= r_scan_word[9:5];     // bits 9..5
        r_wl_sel <= r_scan_word[4:0];     // bits 4..0
      end 
	  r_op_set_d <= r_op_set;
	  r_sl_sel_d <= r_sl_sel;
	  r_wl_sel_d <= r_wl_sel;
	  r_bl_sel_d <= r_bl_sel;   		
	end
  //------------------------------------------------------------------------------------
  
  //------------------------------------------------------------------------------------
  // Functional FSM control and PWM data steering
  //
  // This block selects and drives internal FSM control and PWM data based on
  // the current FSM command, operating mode, and completion status.
  //------------------------------------------------------------------------------------
  always @(posedge i_user_clk or posedge i_user_rst) begin
    if (i_user_rst) begin
      fsm_cntrl_slg <= 3'b000;
    end
    else begin 
	    if((i_scan_se1 == 0) && ( i_TM == 0))begin // scan is inactive 
        if( (fsm_cntrl == 2'b01) || (fsm_cntrl == 2'b10) || (fsm_cntrl == 2'b00) || (fsm_cntrl == 2'b11)) begin 
          if(fsm_cntrl == 2'b01) begin //read mode
            i_fsm_cntrl  <= fsm_cntrl;
	    	    r_pwm_data  <= w_pwm_data;
            fsm_cntrl_slg <= {1'b0, fsm_cntrl};
          end 
          if(fsm_cntrl == 2'b10) begin  	// forming mode      
	          fsm_cntrl_slg <= {1'b0, fsm_cntrl};
		        i_fsm_cntrl  <= fsm_cntrl;
			      r_pwm_data  <= w_pwm_data;
		        if(w_form_read_mode_en)begin
		          fsm_cntrl_slg <= 3'b001;
		          r_pwm_data  <= w_prev_pwm_data;
		          i_fsm_cntrl  <= fsm_cntrl;
		        end  	      
          end	  
          if(fsm_cntrl == 2'b11) begin // set mode
			      fsm_cntrl_slg <= {1'b0, fsm_cntrl};
		        i_fsm_cntrl  <= fsm_cntrl;
			      r_pwm_data  <= w_pwm_data;
	          if(w_pgm_set_read_mode_en)begin 
	            fsm_cntrl_slg <= 3'b001;
		          r_pwm_data  <= w_prev_pwm_data;
		          i_fsm_cntrl  <= fsm_cntrl;
            end 	     
          end    
          if(fsm_cntrl == 2'b00) begin //reset mode
			      fsm_cntrl_slg <= {1'b1, fsm_cntrl};
		        i_fsm_cntrl  <= fsm_cntrl;
			      r_pwm_data  <= w_pwm_data;
	          if( w_pgm_reset_read_mode_en)begin 
	            fsm_cntrl_slg <= 3'b001;
		          r_pwm_data  <= w_prev_pwm_data;
		          i_fsm_cntrl  <= fsm_cntrl;
            end 	     
          end     			
        end
		    else begin
				  w_mode <= 3'b000;
		      i_fsm_cntrl  <= 0;
		    end 
        if(w_read_done || w_form_done || w_pgm_set_done || w_pgm_reset_done)
          w_mode <= 3'b000;
      end
      else begin 
        i_fsm_cntrl  <= 0;
		    r_pwm_data  <= 0;
        fsm_cntrl_slg <= 0;
      end 
    end 
  end 
 //------------------------------------------------------------------------------------
 
  //----------------------------------------------------------------------------------
  // FIFO read enable generation
  //When any operation completion signal (w_read_done, w_form_done,
  //w_pgm_set_done, w_pgm_reset_done) is asserted, w_fifo_ren is set high,
  //----------------------------------------------------------------------------------  
  always @(posedge i_user_clk or posedge i_user_rst ) begin
    if(i_user_rst ) begin 
      w_fifo_ren <= 0;
    end 
    else if( w_read_done || w_form_done  || w_pgm_set_done || w_pgm_reset_done) begin 
      w_fifo_ren <= 1;
    end 
    else  
      w_fifo_ren <= 0;
  end
  //----------------------------------------------------------------------------------  

// TDC instance 
  cnt_top tdc_cnt_top_inst(
    .i_sys_clk     ( i_user_clk      ) ,
    .i_sys_rst     ( i_user_rst      ) ,
    .i_tdc_cnt_rst ( i_user_rst      ) ,
    .i_tdc_rd_en   ( w_tdc_rd_en     ) ,
    .i_tdc_start   ( w_tdc_start     ) ,
    .i_tdc_timeout ( r_time_out_cnt  ) ,
    .i_tdc_dead_tm ( r_dead_time_cnt ) ,
    .i_tdc_stop    ( i_stop_bit      ) ,
    .o_tdc_vld     ( w_tdc_vld       ) ,
    .o_tdc_cnt     ( w_tdc_cnt     ) 
  ) ;
	
// fsm_decoder instance
  fsm_decoder uut_fsm_decoder (
    .i_control_slg       (fsm_cntrl_slg         ),
	.i_fsm_cntrl         (i_fsm_cntrl           ),
    .i_user_clk            (i_user_clk              ),
    .i_pwm_data_in         (r_pwm_data            ),
    .o_pwm_en              (o_pwm_en              ),
    .o_pwm_data_out        (o_pwm_dac_outp          ),
    .i_row_addr            (w_row_addr            ),
    .i_col_addr            (w_col_addr            ),
    .o_err                 (w_err_reg               ),
    .i_r_tdc_inp           (w_r_tdc_cnt             ),
    .i_r_tdc_vld           (w_r_tdc_vld             ),
    .i_rd_full_row         (w_rd_full_row           ),
	.i_fsm_o_start         (w_fsm_start             ),
	.i_target_set1         (w_target_set1           ),
	.i_target_set2         (w_target_set2           ),
	.i_target_reset1       (w_target_reset1         ),
	.i_target_reset2       (w_target_reset2         ),
	.i_no_of_clk_cycles    (w_no_of_clk_cycles      ),
	.i_counter_value       (w_counter_value         ),
    .o_form_read_mode      (w_form_read_mode_en     ),
    .o_pgm_set_read_mode   (w_pgm_set_read_mode_en  ),
    .o_pgm_reset_read_mode (w_pgm_reset_read_mode_en),
	.i_row_addr_pwm        (w_row_addr_pwm        ),
	.i_col_addr_pwm        (w_col_addr_pwm        ),	
    .i_reset_n           (i_user_rst              ),
    .o_mux_Sel             (w_mux_sel_fsm           ),
    .o_data_bl             (w_data_bl               ),
    .o_data_sl             (w_data_sl               ),
    .o_addr_bl             (w_addr_bl               ),
    .o_addr_wl             (w_addr_wl               ),
    .o_addr_sl             (w_addr_sl               ),
    .o_float_wl            (w_float_wl              ),
    .o_float_sl            (w_float_sl              ),
    .o_float_bl            (w_float_bl              ),
    .o_read_done           (w_read_done             ),
    .o_form_done           (w_form_done             ),
    .o_pgm_set_done        (w_pgm_set_done          ),
    .o_pgm_reset_done      (w_pgm_reset_done        ),
    .o_v_count           (o_v_count             ),
    .o_precharge           (o_precharge           ),
    .o_hold                (o_hold                ),
    .o_ramp                (o_ramp                ),
    .o_tdc_o_start           (w_tdc_start           ),
    .o_start               (o_start               )
  );
  
// memory instance
  scratch_pad #(
    .DATA_WIDTH(19),
    .ADDR_WIDTH(10)
  ) scratchpad_inst (
    .clk     (i_user_clk                        ),
    .rst     (i_user_rst                        ),
    .wr_en   (w_tdc_vld                         ),
    .wr_addr ({w_row_addr_pwm, w_col_addr_pwm}  ),
    .wr_data (w_tdc_cnt                         ), 
    .rd_en   (!w_read_en_spd                    ),
    .rd_addr ({w_row_addr_pwm,w_col_addr_pwm}   ),
    .rd_data (w_scratchpad_data_out             ),
    .rd_vld  (w_spd_data_vld                    )
  );
  
  // wb_slv instance  
  Wb_slave wb_inst
  (
    .i_wb_clk         (i_wb_clk             ),
    .i_wb_rst         (i_wb_rst             ),
    .i_wb_cyc         (i_wbs_cyc            ),
    .i_wb_stb         (i_wbs_stb            ),
    .i_wb_we          (i_wbs_we             ),
    .i_wb_addr        (i_wbs_adr            ),
    .i_wb_sel         (i_wbs_sel            ),
    .i_wb_data        (i_wbs_dat            ),
    .o_target_set1    (w_target_set1        ),
    .o_target_set2    (w_target_set2        ),
    .o_target_reset1  (w_target_reset1      ),
    .o_target_reset2  (w_target_reset2      ),
    .o_no_clk_cycles  (w_no_of_clk_cycles   ),
    .o_tdc_time_out   (r_time_out_cnt       ),
    .o_tdc_dead_time  (r_dead_time_cnt      ),
    .o_counter_value  (w_counter_value      ), 		
    .o_wb_ack         (o_wbs_ack            ),
    .o_wb_data        (o_wbs_data           ),
	.i_usr_clk        (i_user_clk           ),
	.i_usr_rst        (i_user_rst           ),
    .i_fifo_ren       (w_fifo_ren           ),
    .o_mode_sel       (fsm_cntrl            ),
    .o_row_addr_fsm   (w_row_addr           ),
    .o_col_addr_fsm   (w_col_addr           ),
    .o_pwm_inp        (w_pwm_data           ),
    .o_prev_pwm_inp   (w_prev_pwm_data      ),
    .i_rd_fifo_wr_en  (w_spd_data_vld       ),
	.o_start_fsm      (w_fsm_start          ),
	.i_err_reg        (w_err_reg            ),
    .o_rd_full        (w_read_en_spd        ),
    .o_rd_full_row    (w_rd_full_row        ),
    .i_rd_fifo_datain (w_scratchpad_data_out)
  );


//Scan debug instance 
  ScanDebug  #(.N(32))ScanDebug_inst(
    .i_op_set    ( r_op_set_d ),
    .i_wl_sel    ( r_wl_sel_d ),
    .i_bl_sel    ( r_bl_sel_d ),
    .i_sl_sel    ( r_sl_sel_d ),
    .o_WL_Float  ( w_WL_Float ), 
    .o_WL_EN_L   ( w_WL_EN_L  ),  
    .o_Data_wl   ( w_Data_wl  ), 
    .o_WL_addr   ( w_WL_addr  ), 
    .o_BL_Float  ( w_BL_Float ), 
    .o_BL_EN_L   ( w_BL_EN_L  ),
    .o_Data_bl   ( w_Data_bl  ),
    .o_BL_addr   ( w_BL_addr  ),
    .o_SL_Float  ( w_SL_Float ),
    .o_SL_EN_L   ( w_SL_EN_L  ),
    .o_Data_sl   ( w_Data_sl  ),
    .o_SL_addr   ( w_SL_addr  ),
    .o_Mux_sel   ( w_mux_sel  )		
	); 
endmodule
